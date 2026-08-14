import logging
import queue
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class PairVerdict(Enum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    INVALID = "invalid"


class ScanTerminalState(Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INVALID = "invalid"
    ERROR = "error"


@dataclass(frozen=True)
class ScanProfile:
    frequency_hz: float = 440.0
    output_peak: float = 0.5
    baseline_duration_s: float = 0.1
    tone_duration_s: float = 0.1
    tail_duration_s: float = 0.2
    settle_duration_s: float = 0.8
    absolute_threshold_dbfs: float = -80.0
    minimum_margin_db: float = 12.0
    clip_level: float = 0.999999

    @property
    def output_level_dbfs(self) -> float:
        return 20.0 * np.log10(self.output_peak)


@dataclass(frozen=True)
class PairMeasurement:
    output_channel: int
    input_channel: int
    level_dbfs: float
    baseline_dbfs: float
    margin_db: float
    verdict: PairVerdict


@dataclass(frozen=True)
class ScanResult:
    state: ScanTerminalState
    measurements: tuple[PairMeasurement, ...]
    profile: ScanProfile
    input_device_name: str = ""
    output_device_name: str = ""
    sample_rate: float = 0.0
    input_channels: int = 0
    output_channels: int = 0
    completed_outputs: int = 0
    clipped_inputs: tuple[int, ...] = ()
    io_errors: tuple[str, ...] = ()
    error_message: str = ""

    @property
    def detected_count(self) -> int:
        return sum(item.verdict == PairVerdict.DETECTED for item in self.measurements)


class _BufferHandoffError(RuntimeError):
    pass


class LoopbackWorker(QThread):
    progress = pyqtSignal(int, str)
    completed = pyqtSignal(object)

    def __init__(
        self,
        module: "LoopbackFinder",
        device_id: tuple[object, object],
        sample_rate: float,
        profile: ScanProfile,
    ):
        super().__init__()
        self.module = module
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.profile = profile
        self._cancel_event = threading.Event()
        self._stream_lock = threading.Lock()
        self._stream = None

    def run(self) -> None:
        try:
            result = self.module.perform_scan(
                self.device_id,
                self.sample_rate,
                self.profile,
                self._cancel_event,
                self.progress.emit,
                self._register_stream,
            )
        except Exception as exc:
            logger.error("Loopback scan failed: %s", exc, exc_info=True)
            result = ScanResult(
                state=ScanTerminalState.ERROR,
                measurements=(),
                profile=self.profile,
                sample_rate=self.sample_rate,
                error_message=str(exc),
            )
        finally:
            self._register_stream(None)
        self.completed.emit(result)

    def _register_stream(self, stream) -> None:
        with self._stream_lock:
            self._stream = stream

    def stop(self) -> None:
        self._cancel_event.set()
        with self._stream_lock:
            stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception as exc:
                logger.debug("Failed to abort loopback scan stream: %s", exc)


class LoopbackFinder(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.worker: LoopbackWorker | None = None
        self.profile = ScanProfile()

    @property
    def name(self) -> str:
        return "Loopback Finder"

    @property
    def description(self) -> str:
        return "Detects active loopback paths between output and input channels."

    def _get_device_info(self, device_id: object, cached_devices: object):
        if device_id is None:
            raise ValueError(tr("Select both an input and output device."))

        devices: Sequence | None = None
        if isinstance(cached_devices, Sequence) and not isinstance(cached_devices, (str, bytes, dict)):
            devices = cached_devices

        if devices is not None and isinstance(device_id, int) and 0 <= device_id < len(devices):
            return devices[device_id]

        if devices is not None and isinstance(device_id, str):
            query = device_id.casefold()
            query_parts = query.split()
            for device in devices:
                name = str(device.get("name", ""))
                if name.casefold() == query:
                    return device
            for device in devices:
                name = str(device.get("name", "")).casefold()
                if all(part in name for part in query_parts):
                    return device

        return sd.query_devices(device_id)

    def _resolve_scan_devices(self, device_id: tuple[object, object]):
        if not isinstance(device_id, tuple) or len(device_id) != 2:
            raise ValueError(tr("Select both an input and output device."))
        input_device, output_device = device_id

        try:
            devices, _ = self.audio_engine._get_cached_audio_info()
        except Exception as exc:
            logger.warning("Failed to get cached audio info: %s", exc)
            try:
                devices = sd.query_devices()
            except Exception:
                devices = None

        input_info = self._get_device_info(input_device, devices)
        output_info = self._get_device_info(output_device, devices)
        max_in = int(input_info["max_input_channels"])
        max_out = int(output_info["max_output_channels"])
        if max_in <= 0 or max_out <= 0:
            raise ValueError(tr("The selected devices must provide at least one input and one output channel."))

        return input_info, output_info, max_in, max_out

    @staticmethod
    def _coherent_amplitude(samples: np.ndarray, reference: np.ndarray) -> float:
        if samples.size != reference.size or samples.size == 0:
            return 0.0
        return float(2.0 * np.abs(np.dot(samples, reference)) / samples.size)

    def _analyze_output_buffer(
        self,
        buffer: np.ndarray,
        output_channel: int,
        sample_rate: float,
        profile: ScanProfile,
        reference: np.ndarray,
        baseline_frames: int,
        tone_frames: int,
    ) -> tuple[list[PairMeasurement], set[int]]:
        measurements: list[PairMeasurement] = []
        clipped_inputs: set[int] = set()
        response = buffer[baseline_frames:]
        hop = max(1, tone_frames // 4)
        final_start = max(0, response.shape[0] - tone_frames)
        window_starts = list(range(0, final_start + 1, hop))
        if not window_starts or window_starts[-1] != final_start:
            window_starts.append(final_start)

        for input_index in range(buffer.shape[1]):
            input_channel = input_index + 1
            samples = buffer[:, input_index]
            if samples.size and float(np.max(np.abs(samples))) >= profile.clip_level:
                clipped_inputs.add(input_channel)

            baseline_amplitude = self._coherent_amplitude(samples[:baseline_frames], reference)
            response_amplitude = max(
                (
                    self._coherent_amplitude(response[start : start + tone_frames, input_index], reference)
                    for start in window_starts
                ),
                default=0.0,
            )
            baseline_dbfs = 20.0 * np.log10(max(baseline_amplitude, 1e-12))
            level_dbfs = 20.0 * np.log10(max(response_amplitude, 1e-12))
            margin_db = level_dbfs - baseline_dbfs

            above_absolute = level_dbfs >= profile.absolute_threshold_dbfs
            above_baseline = margin_db >= profile.minimum_margin_db
            if above_absolute and above_baseline:
                verdict = PairVerdict.DETECTED
            else:
                verdict = PairVerdict.NOT_DETECTED

            measurements.append(
                PairMeasurement(
                    output_channel=output_channel,
                    input_channel=input_channel,
                    level_dbfs=level_dbfs,
                    baseline_dbfs=baseline_dbfs,
                    margin_db=margin_db,
                    verdict=verdict,
                )
            )
        return measurements, clipped_inputs

    def perform_scan(
        self,
        device_id: tuple[object, object],
        sample_rate: float,
        profile: ScanProfile,
        cancel_event: threading.Event,
        progress_callback: Callable[[int, str], None] | None = None,
        stream_callback: Callable[[object], None] | None = None,
    ) -> ScanResult:
        sample_rate = float(sample_rate)
        if not np.isfinite(sample_rate) or sample_rate <= 2.0 * profile.frequency_hz:
            raise ValueError(tr("The sample rate is not valid for the loopback test signal."))

        input_info, output_info, max_in, max_out = self._resolve_scan_devices(device_id)
        input_name = str(input_info.get("name", device_id[0]))
        output_name = str(output_info.get("name", device_id[1]))

        baseline_frames = max(1, int(round(sample_rate * profile.baseline_duration_s)))
        tone_frames = max(1, int(round(sample_rate * profile.tone_duration_s)))
        tail_frames = max(1, int(round(sample_rate * profile.tail_duration_s)))
        step_frames = baseline_frames + tone_frames + tail_frames
        settle_frames = max(0, int(round(sample_rate * profile.settle_duration_s)))

        phase = np.arange(tone_frames, dtype=np.float64)
        test_signal = (profile.output_peak * np.sin(2.0 * np.pi * profile.frequency_hz * phase / sample_rate)).astype(
            np.float32
        )
        reference = np.exp(-2j * np.pi * profile.frequency_hz * phase / sample_rate)

        free_buffers: queue.Queue[np.ndarray] = queue.Queue(maxsize=3)
        ready_buffers: queue.Queue[tuple[int, np.ndarray]] = queue.Queue(maxsize=3)
        for _ in range(3):
            free_buffers.put(np.zeros((step_frames, max_in), dtype=np.float32))

        current_buffer = free_buffers.get_nowait()
        current_output = 0
        current_frame = 0
        settled_frames = 0
        stream_error: list[Exception | None] = [None]
        io_errors: set[str] = set()
        stream_finished = threading.Event()

        def callback(indata, outdata, frames, time_info, status):
            nonlocal current_buffer, current_output, current_frame, settled_frames
            del time_info
            try:
                outdata.fill(0)
                if cancel_event.is_set() or current_output >= max_out:
                    raise sd.CallbackStop()

                for flag_name in ("input_underflow", "input_overflow", "output_underflow", "output_overflow"):
                    if bool(getattr(status, flag_name, False)):
                        io_errors.add(flag_name)

                processed = 0
                if settled_frames < settle_frames:
                    consume = min(frames, settle_frames - settled_frames)
                    settled_frames += consume
                    processed += consume

                while processed < frames:
                    if cancel_event.is_set() or current_output >= max_out:
                        raise sd.CallbackStop()

                    write_size = min(frames - processed, step_frames - current_frame)
                    current_buffer[current_frame : current_frame + write_size, :] = indata[
                        processed : processed + write_size, :max_in
                    ]

                    tone_start = baseline_frames
                    tone_end = baseline_frames + tone_frames
                    overlap_start = max(current_frame, tone_start)
                    overlap_end = min(current_frame + write_size, tone_end)
                    if overlap_end > overlap_start:
                        out_start = processed + overlap_start - current_frame
                        signal_start = overlap_start - tone_start
                        count = overlap_end - overlap_start
                        outdata[out_start : out_start + count, current_output] = test_signal[
                            signal_start : signal_start + count
                        ]

                    current_frame += write_size
                    processed += write_size

                    if current_frame >= step_frames:
                        try:
                            ready_buffers.put_nowait((current_output + 1, current_buffer))
                        except queue.Full as exc:
                            raise _BufferHandoffError("analysis_queue_overrun") from exc
                        current_output += 1
                        current_frame = 0
                        if current_output >= max_out:
                            raise sd.CallbackStop()
                        try:
                            current_buffer = free_buffers.get_nowait()
                        except queue.Empty as exc:
                            raise _BufferHandoffError("analysis_buffer_overrun") from exc
                        current_buffer.fill(0)
            except sd.CallbackStop:
                raise
            except Exception as exc:
                stream_error[0] = exc
                raise sd.CallbackAbort() from exc

        if progress_callback:
            progress_callback(0, tr("Starting connection..."))

        try:
            stream = sd.Stream(
                device=device_id,
                samplerate=sample_rate,
                channels=(max_in, max_out),
                dtype="float32",
                callback=callback,
                finished_callback=stream_finished.set,
            )
        except Exception as exc:
            raise RuntimeError(tr("Unable to open the loopback scan stream: {0}").format(str(exc))) from exc

        if stream_callback:
            stream_callback(stream)

        measurements: list[PairMeasurement] = []
        clipped_inputs: set[int] = set()
        completed_outputs = 0
        with stream:
            while True:
                if cancel_event.is_set() and stream.active:
                    stream.abort()

                try:
                    output_channel, buffer = ready_buffers.get(timeout=0.05)
                except queue.Empty:
                    if (stream_finished.is_set() or not stream.active) and ready_buffers.empty():
                        break
                    continue

                output_measurements, output_clipping = self._analyze_output_buffer(
                    buffer,
                    output_channel,
                    sample_rate,
                    profile,
                    reference,
                    baseline_frames,
                    tone_frames,
                )
                measurements.extend(output_measurements)
                clipped_inputs.update(output_clipping)
                completed_outputs += 1
                buffer.fill(0)
                free_buffers.put_nowait(buffer)

                if progress_callback:
                    progress = int(100 * completed_outputs / max_out)
                    if completed_outputs < max_out:
                        message = tr("Testing Output Channel {0} of {1}").format(completed_outputs + 1, max_out)
                    else:
                        message = tr("Finalizing scan...")
                    progress_callback(progress, message)

        if stream_callback:
            stream_callback(None)

        if isinstance(stream_error[0], _BufferHandoffError):
            io_errors.add(str(stream_error[0]))
        elif stream_error[0] is not None and not cancel_event.is_set():
            raise RuntimeError(tr("Loopback scan callback failed: {0}").format(str(stream_error[0])))

        if cancel_event.is_set():
            state = ScanTerminalState.CANCELLED
            measurements = [replace(item, verdict=PairVerdict.INVALID) for item in measurements]
        elif io_errors:
            state = ScanTerminalState.INVALID
            measurements = [replace(item, verdict=PairVerdict.INVALID) for item in measurements]
        elif clipped_inputs:
            state = ScanTerminalState.INVALID
            measurements = [
                replace(item, verdict=PairVerdict.INVALID) if item.input_channel in clipped_inputs else item
                for item in measurements
            ]
        else:
            state = ScanTerminalState.COMPLETED

        return ScanResult(
            state=state,
            measurements=tuple(measurements),
            profile=profile,
            input_device_name=input_name,
            output_device_name=output_name,
            sample_rate=sample_rate,
            input_channels=max_in,
            output_channels=max_out,
            completed_outputs=completed_outputs,
            clipped_inputs=tuple(sorted(clipped_inputs)),
            io_errors=tuple(sorted(io_errors)),
        )

    def get_widget(self):
        return LoopbackFinderWidget(self)


class LoopbackFinderWidget(QWidget):
    def __init__(self, module: LoopbackFinder):
        super().__init__()
        self.module = module
        self._scan_available = True
        self._engine_was_active = False
        self._engine_restored = True
        self._last_result: ScanResult | None = None
        self.init_ui()

    def init_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setDirection(QBoxLayout.Direction.LeftToRight)

        self.results_group = QGroupBox(tr("Connection Matrix"))
        results_layout = QVBoxLayout(self.results_group)
        result_header = QHBoxLayout()
        self.summary_label = QLabel(tr("No scan results."))
        self.summary_label.setStyleSheet("font-weight: bold;")
        result_header.addWidget(self.summary_label)
        result_header.addStretch(1)
        self.validity_label = QLabel("")
        result_header.addWidget(self.validity_label)
        results_layout.addLayout(result_header)

        self.results_table = QTableWidget(0, 0)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        results_layout.addWidget(self.results_table, stretch=1)

        legend = QLabel(tr("✓ detected   value only: not detected   ! invalid"))
        legend.setWordWrap(True)
        results_layout.addWidget(legend)

        self.control_panel = QWidget()
        self.control_panel.setMinimumWidth(360)
        self.control_panel.setMaximumWidth(400)
        controls = QVBoxLayout(self.control_panel)

        caution = QLabel(tr("An active measurement is paused during the scan and restored when it finishes."))
        caution.setWordWrap(True)
        caution.setStyleSheet("font-weight: bold;")
        controls.addWidget(caution)

        measurement_group = QGroupBox(tr("Scan"))
        measurement_layout = QVBoxLayout(measurement_group)
        self.start_btn = QPushButton(tr("Start Scan"))
        self.start_btn.clicked.connect(self.start_scan)
        measurement_layout.addWidget(self.start_btn)
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        measurement_layout.addWidget(self.stop_btn)
        self.status_label = QLabel(tr("Ready"))
        self.status_label.setWordWrap(False)
        measurement_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        measurement_layout.addWidget(self.progress_bar)
        controls.addWidget(measurement_group)

        conditions_group = QGroupBox(tr("Scan Conditions"))
        self.conditions_layout = QFormLayout(conditions_group)
        self.conditions_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.conditions_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.input_device_label = QLabel("—")
        self.input_device_label.setWordWrap(False)
        self.output_device_label = QLabel("—")
        self.output_device_label.setWordWrap(False)
        self.sample_rate_label = QLabel("—")
        self.stimulus_label = QLabel(
            tr("{0:g} Hz at {1:.2f} dBFS").format(
                self.module.profile.frequency_hz, self.module.profile.output_level_dbfs
            )
        )
        self.stimulus_label.setWordWrap(False)
        self.conditions_layout.addRow(tr("Input Device:"), self.input_device_label)
        self.conditions_layout.addRow(tr("Output Device:"), self.output_device_label)
        self.conditions_layout.addRow(tr("Rate:"), self.sample_rate_label)
        self.conditions_layout.addRow(tr("Test Signal:"), self.stimulus_label)
        controls.addWidget(conditions_group)

        self.clipping_warning = QLabel(tr("ADC CLIPPING — affected input results are invalid."))
        self.clipping_warning.setWordWrap(True)
        self.clipping_warning.setStyleSheet("color: #ff4040; font-weight: bold;")
        self.clipping_warning.hide()
        controls.addWidget(self.clipping_warning)

        self.io_warning = QLabel(tr("I/O BUFFER ERROR — scan results are invalid."))
        self.io_warning.setWordWrap(True)
        self.io_warning.setStyleSheet("color: #ff9f1a; font-weight: bold;")
        self.io_warning.hide()
        controls.addWidget(self.io_warning)

        self.restore_warning = QLabel(tr("The previous audio stream could not be restored."))
        self.restore_warning.setWordWrap(True)
        self.restore_warning.setStyleSheet("color: #ff9f1a; font-weight: bold;")
        self.restore_warning.hide()
        controls.addWidget(self.restore_warning)

        controls.addStretch(1)
        root.addWidget(self.control_panel, stretch=1)
        root.addWidget(self.results_group, stretch=4)
        self._refresh_conditions()
        self._update_availability()

    def _format_device(self, device_id: object) -> str:
        if device_id is None:
            return tr("Not selected")
        try:
            devices, _ = self.module.audio_engine._get_cached_audio_info()
            info = self.module._get_device_info(device_id, devices)
            return str(info.get("name", device_id))
        except Exception:
            return str(device_id)

    def _refresh_conditions(self) -> None:
        engine = self.module.audio_engine
        input_text = self._format_device(engine.input_device)
        output_text = self._format_device(engine.output_device)
        self.input_device_label.setText(input_text)
        self.input_device_label.setToolTip(input_text)
        self.output_device_label.setText(output_text)
        self.output_device_label.setToolTip(output_text)
        self.sample_rate_label.setText(tr("{0:g} Hz").format(float(engine.sample_rate)))

    def _update_availability(self) -> None:
        engine = self.module.audio_engine
        reason = ""
        if bool(getattr(engine, "offline_mode", False)):
            reason = tr("Virtual mode cannot scan physical loopback paths.")
        elif engine.input_device is None or engine.output_device is None:
            reason = tr("Select both an input and output device.")
        elif not np.isfinite(float(engine.sample_rate)) or float(engine.sample_rate) <= 2 * self.module.profile.frequency_hz:
            reason = tr("The sample rate is not valid for the loopback test signal.")

        self._scan_available = not reason
        running = self.module.worker is not None and self.module.worker.isRunning()
        self.start_btn.setEnabled(self._scan_available and not running)
        if reason and not running:
            self.status_label.setText(reason)
        elif not running:
            self.status_label.setText(tr("Ready"))

    def showEvent(self, event) -> None:
        self._refresh_conditions()
        self._update_availability()
        super().showEvent(event)

    def start_scan(self) -> None:
        self._refresh_conditions()
        self._update_availability()
        if not self._scan_available or (self.module.worker is not None and self.module.worker.isRunning()):
            return

        self._last_result = None
        self.clipping_warning.hide()
        self.io_warning.hide()
        self.restore_warning.hide()
        self.summary_label.setText(tr("Scanning..."))
        self.validity_label.clear()
        self.results_table.setRowCount(0)
        self.results_table.setColumnCount(0)
        self.progress_bar.setValue(0)
        self.status_label.setText(tr("Starting connection..."))
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        engine = self.module.audio_engine
        self._engine_was_active = bool(engine.is_active())
        self._engine_restored = False
        if self._engine_was_active:
            engine.stop_stream()

        worker = LoopbackWorker(
            self.module,
            (engine.input_device, engine.output_device),
            float(engine.sample_rate),
            self.module.profile,
        )
        self.module.worker = worker
        worker.progress.connect(self.update_progress)
        worker.completed.connect(self._on_scan_completed)
        worker.start()

    def stop_scan(self) -> None:
        worker = self.module.worker
        if worker is None or not worker.isRunning():
            return
        self.stop_btn.setEnabled(False)
        self.status_label.setText(tr("Stopping scan..."))
        worker.stop()

    def update_progress(self, value: int, message: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def _restore_audio_engine(self) -> bool:
        if self._engine_restored:
            return True
        self._engine_restored = True
        if not self._engine_was_active:
            return True
        try:
            restored = self.module.audio_engine.ensure_stream_running()
        except Exception as exc:
            logger.error("Failed to restore main audio engine: %s", exc, exc_info=True)
            restored = False
        self.restore_warning.setVisible(not restored)
        return restored

    def _on_scan_completed(self, result: ScanResult) -> None:
        worker = self.module.worker
        self.module.worker = None
        if worker is not None:
            worker.deleteLater()

        self._last_result = result
        self._restore_audio_engine()
        self.start_btn.setEnabled(self._scan_available)
        self.stop_btn.setEnabled(False)
        self._update_conditions_from_result(result)
        self._render_result(result)

        if result.state == ScanTerminalState.COMPLETED:
            self.progress_bar.setValue(100)
            self.validity_label.setText(tr("VALID"))
            self.validity_label.setStyleSheet("color: #2e7d32; font-weight: bold;")
        elif result.state == ScanTerminalState.CANCELLED:
            self.validity_label.setText(tr("CANCELLED"))
            self.validity_label.setStyleSheet("color: #ff9f1a; font-weight: bold;")
            self.summary_label.setText(
                tr("Scan cancelled after {0} of {1} output channels. Partial results are invalid.").format(
                    result.completed_outputs, result.output_channels
                )
            )
        elif result.state == ScanTerminalState.INVALID:
            self.progress_bar.setValue(100 if result.completed_outputs == result.output_channels else self.progress_bar.value())
            self.validity_label.setText(tr("INVALID"))
            self.validity_label.setStyleSheet("color: #ff4040; font-weight: bold;")
            self.summary_label.setText(tr("Scan invalid — review the warnings below."))
        else:
            self.validity_label.setText(tr("ERROR"))
            self.validity_label.setStyleSheet("color: #ff4040; font-weight: bold;")
            self.summary_label.setText(tr("Scan failed: {0}").format(result.error_message))

        self.status_label.setText(tr("Ready"))
        self.clipping_warning.setVisible(bool(result.clipped_inputs))
        self.io_warning.setVisible(bool(result.io_errors))

    def _update_conditions_from_result(self, result: ScanResult) -> None:
        if result.input_device_name:
            self.input_device_label.setText(result.input_device_name)
            self.input_device_label.setToolTip(result.input_device_name)
        if result.output_device_name:
            self.output_device_label.setText(result.output_device_name)
            self.output_device_label.setToolTip(result.output_device_name)
        if result.sample_rate:
            self.sample_rate_label.setText(tr("{0:g} Hz").format(result.sample_rate))

    def _render_result(self, result: ScanResult) -> None:
        self.results_table.setRowCount(result.output_channels)
        self.results_table.setColumnCount(result.input_channels)
        self.results_table.setVerticalHeaderLabels(
            [tr("Output {0}").format(index) for index in range(1, result.output_channels + 1)]
        )
        self.results_table.setHorizontalHeaderLabels(
            [tr("Input {0}").format(index) for index in range(1, result.input_channels + 1)]
        )

        by_pair = {(item.output_channel, item.input_channel): item for item in result.measurements}
        for output_channel in range(1, result.output_channels + 1):
            for input_channel in range(1, result.input_channels + 1):
                measurement = by_pair.get((output_channel, input_channel))
                item = self._measurement_item(measurement)
                self.results_table.setItem(output_channel - 1, input_channel - 1, item)

        if result.measurements:
            self.summary_label.setText(tr("Detected paths: {0}").format(result.detected_count))
        else:
            self.summary_label.setText(tr("No scan results."))

    def _measurement_item(self, measurement: PairMeasurement | None) -> QTableWidgetItem:
        if measurement is None:
            item = QTableWidgetItem("—")
            item.setForeground(QColor("#777777"))
            return item

        if measurement.verdict == PairVerdict.DETECTED:
            text = f"✓ {measurement.level_dbfs:.1f}"
            color = "#2e7d32"
        elif measurement.verdict == PairVerdict.INVALID:
            text = "!"
            color = "#d32f2f"
        else:
            text = f"{measurement.level_dbfs:.1f}" if measurement.level_dbfs > -180.0 else "—"
            color = "#777777"

        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(QColor(color))
        item.setToolTip(
            "\n".join(
                [
                    tr("Received Level: {0:.1f} dBFS").format(measurement.level_dbfs),
                    tr("Baseline: {0:.1f} dBFS").format(measurement.baseline_dbfs),
                    tr("Detection Margin: {0:.1f} dB").format(measurement.margin_db),
                ]
            )
        )
        return item

    def closeEvent(self, event) -> None:
        worker = self.module.worker
        if worker is not None and worker.isRunning():
            worker.stop()
            if not worker.wait(2000):
                logger.warning("Loopback scan worker did not stop before the close timeout")
                event.ignore()
                return
        self.module.worker = None
        self._restore_audio_engine()
        super().closeEvent(event)
