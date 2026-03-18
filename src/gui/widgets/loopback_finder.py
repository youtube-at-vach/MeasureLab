import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


class LoopbackWorker(QThread):
    progress = pyqtSignal(int, str)
    result = pyqtSignal(list)
    error = pyqtSignal(str)
    finished_testing = pyqtSignal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.is_running = True

    def run(self):
        try:
            stream = self.ctx["stream"]
            stream_finished = self.ctx["stream_finished"]
            stream_error = self.ctx["stream_error"]

            with stream:
                while stream.active:
                    if stream_finished.wait(0.1):
                        break
                    if not self.is_running:
                        stream.abort()
                        break

            if stream_error[0]:
                raise Exception(f"Callback error: {stream_error[0]}")

            self.result.emit(self.ctx["found_paths"])
            self.finished_testing.emit()
        except Exception as e:
            self.error.emit(str(e))

    def report_progress(self, value, message):
        self.progress.emit(value, message)

    def stop(self):
        self.is_running = False


class LoopbackFinder(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.worker = None

    @property
    def name(self) -> str:
        return "Loopback Finder"

    @property
    def description(self) -> str:
        return "Detects active loopback paths between output and input channels."

    def prepare_scan(self, device_id, sample_rate, progress_callback=None):
        if isinstance(device_id, tuple):
            input_device, output_device = device_id
            in_info = sd.query_devices(input_device)
            out_info = sd.query_devices(output_device)
            max_in = in_info["max_input_channels"]
            max_out = out_info["max_output_channels"]
        else:
            device_info = sd.query_devices(device_id)
            max_out = device_info["max_output_channels"]
            max_in = device_info["max_input_channels"]

        if max_out == 0 or max_in == 0:
            raise Exception(f"Device {device_id} does not support both input and output.")

        found_paths = []
        test_freq = 440
        tone_duration = 0.1
        listen_padding = 0.2  # Allow latency/tail capture
        step_duration = tone_duration + listen_padding

        tone_frames = int(sample_rate * tone_duration)
        step_frames = int(sample_rate * step_duration)

        # Wait a short duration to let JACK/PipeWire routing establish
        settle_duration = 0.8
        settle_frames = int(sample_rate * settle_duration)

        t = np.linspace(0, tone_duration, tone_frames, False, dtype=np.float32)
        test_signal = 0.5 * np.sin(2 * np.pi * test_freq * t)

        freqs = fft_manager.rfftfreq(step_frames, 1 / sample_rate)
        target_bin = np.argmin(np.abs(freqs - test_freq))
        threshold = 0.01  # -40dBFS approx

        current_out_ch = 0
        current_frame = 0
        settle_passed = 0

        rec_buffer = np.zeros((step_frames, max_in), dtype=np.float32)
        stream_error = [None]

        def callback(indata, outdata, frames, time_info, status):
            nonlocal current_out_ch, current_frame, settle_passed, rec_buffer
            try:
                outdata.fill(0)

                if current_out_ch >= max_out:
                    raise sd.CallbackStop()

                frames_processed = 0
                if settle_passed < settle_frames:
                    rem_settle = settle_frames - settle_passed
                    consume = min(frames, rem_settle)
                    settle_passed += consume
                    frames_processed += consume

                while frames_processed < frames:
                    if current_out_ch >= max_out:
                        raise sd.CallbackStop()

                    rem_in_step = step_frames - current_frame
                    write_size = min(frames - frames_processed, rem_in_step)

                    rec_start = current_frame
                    rec_end = current_frame + write_size
                    in_start = frames_processed
                    in_end = frames_processed + write_size

                    # Store recording, up to max_in channels to prevent slice errors
                    rec_buffer[rec_start:rec_end, :] = indata[in_start:in_end, :max_in]

                    # Output tone
                    tone_rem = tone_frames - current_frame
                    if tone_rem > 0:
                        tone_write = min(write_size, tone_rem)
                        outdata[in_start : in_start + tone_write, current_out_ch] = test_signal[
                            current_frame : current_frame + tone_write
                        ]

                    current_frame += write_size
                    frames_processed += write_size

                    if current_frame >= step_frames:
                        # Process the recorded buffer to find paths
                        for in_ch in range(max_in):
                            input_fft = fft_manager.rfft(rec_buffer[:, in_ch])
                            # Normalize by tone_frames so the magnitude scale matches older implementation
                            magnitude = np.abs(input_fft[target_bin]) / tone_frames * 2
                            if magnitude > threshold:
                                found_paths.append((current_out_ch + 1, in_ch + 1, magnitude))

                        current_out_ch += 1
                        current_frame = 0
                        rec_buffer.fill(0)

                        # Update UI
                        if progress_callback:
                            display_ch = min(current_out_ch + 1, max_out)
                            progress_callback(
                                int((current_out_ch / max_out) * 100),
                                tr("Testing Output Channel {}").format(display_ch),
                            )

            except sd.CallbackStop:
                raise
            except Exception as e:
                stream_error[0] = e
                raise sd.CallbackAbort() from e

        if progress_callback:
            progress_callback(0, tr("Starting connection..."))

        import threading

        stream_finished = threading.Event()

        try:
            stream = sd.Stream(
                device=device_id,
                samplerate=sample_rate,
                channels=(max_in, max_out),
                dtype="float32",
                callback=callback,
                finished_callback=stream_finished.set,
            )
        except Exception as e:
            raise Exception(f"Stream error: {str(e)}") from e

        return {
            "stream": stream,
            "stream_finished": stream_finished,
            "stream_error": stream_error,
            "found_paths": found_paths,
        }

    def get_widget(self):
        return LoopbackFinderWidget(self)


class LoopbackFinderWidget(QWidget):
    def __init__(self, module: LoopbackFinder):
        super().__init__()
        self.module = module
        self._scan_available = True
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Instructions
        layout.addWidget(
            QLabel(
                tr("This tool plays a test tone on each output channel and checks all input channels for the signal.")
            )
        )
        layout.addWidget(QLabel(f"<b>{tr('Note:')}</b> {tr('This will stop the main audio engine temporarily.')}"))

        # Controls
        controls_layout = QHBoxLayout()
        self.start_btn = QPushButton(tr("Start Scan"))
        self.start_btn.clicked.connect(self.start_scan)
        controls_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_btn)

        layout.addLayout(controls_layout)

        # Progress
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel(tr("Ready"))
        layout.addWidget(self.status_label)

        # Results Table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels([tr("Output Channel"), tr("Input Channel"), tr("Signal Level")])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results_table)

        self.setLayout(layout)

        self._update_availability()

    def _update_availability(self):
        # Now fully supports JACK resident mode because we use a continuous stream
        # that allows WirePlumber routing to patch the device during the test.
        self._scan_available = True
        self.start_btn.setEnabled(True)
        self.status_label.setText(tr("Ready"))

    def start_scan(self):
        # Stop main engine if running
        if self.module.audio_engine.stream and self.module.audio_engine.stream.active:
            self.module.audio_engine.stop_stream()

        # Get current device from engine
        # Note: AudioEngine stores device IDs.
        input_device = self.module.audio_engine.input_device
        output_device = self.module.audio_engine.output_device
        device_arg = (input_device, output_device)

        # Temporary worker to allow progress_callback binding
        temp_worker = LoopbackWorker(None)

        try:
            ctx = self.module.prepare_scan(
                device_arg, self.module.audio_engine.sample_rate, progress_callback=temp_worker.report_progress
            )
            temp_worker.ctx = ctx
            self.module.worker = temp_worker
        except Exception as e:
            self.show_error(str(e))
            return

        self.module.worker.progress.connect(self.update_progress)
        self.module.worker.result.connect(self.show_results)
        self.module.worker.error.connect(self.show_error)
        self.module.worker.finished_testing.connect(self.scan_finished)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.results_table.setRowCount(0)
        self.module.worker.start()

    def stop_scan(self):
        if self.module.worker:
            self.module.worker.stop()
            self.module.worker.wait()
        self.scan_finished()

    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def show_results(self, paths):
        self.results_table.setRowCount(len(paths))
        for i, (out_ch, in_ch, mag) in enumerate(paths):
            self.results_table.setItem(i, 0, QTableWidgetItem(str(out_ch)))
            self.results_table.setItem(i, 1, QTableWidgetItem(str(in_ch)))
            self.results_table.setItem(i, 2, QTableWidgetItem(f"{20 * np.log10(mag):.1f} dB"))

        if not paths:
            self.status_label.setText(tr("No loopback paths found."))
        else:
            self.status_label.setText(tr("Found {} loopback paths.").format(len(paths)))

    def show_error(self, message):
        QMessageBox.critical(self, tr("Error"), message)
        self.scan_finished()

    def scan_finished(self):
        self.start_btn.setEnabled(self._scan_available)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
