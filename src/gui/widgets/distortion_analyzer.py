from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc, get_cached_window
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.fft_manager import fft_manager


class DistortionAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 16384  # Larger buffer for better frequency resolution
        self.input_data = np.zeros(self.buffer_size)

        # Generator Settings
        self.gen_frequency = 1000.0
        self.snap_to_bin_center = False
        self._gen_amplitude = 0.5  # Linear 0-1
        self.output_channel = 0  # 0: Left, 1: Right
        self.input_channel = 0  # 0: Left, 1: Right
        self.output_enabled = True

        # Analysis Settings
        self.window_type = "blackmanharris"  # Good for distortion
        self.average_count = 1

        # IMD Settings
        self.imd_standard = "smpte"  # 'smpte' or 'ccif'
        self.imd_f1 = 60.0
        self.imd_f2 = 7000.0
        self.imd_ratio = 4.0  # 4:1 for SMPTE

        # Playback state
        self._phase_f1 = 0.0
        self._phase_f2 = 0.0
        self._phase_accumulator = 0.0

        # Mode
        self.mode = "Real-time"
        self.signal_type = "sine"  # 'sine', 'smpte', 'ccif'

        # State
        self.current_result = None
        self._avg_thdn = None
        self._result_history = deque()
        self._imd_history = deque()
        self._spectrum_history = deque()

        # Capture State
        self.capture_requested = False
        self.capture_ready = False
        self.captured_buffer = None

        # Sweep State
        self.sweep_mode = False
        self.sweep_running = False
        self.sweep_results = []

        self.callback_id = None

    def reset_averaging_state(self):
        """Clear cached averaging state when settings change."""
        self._result_history.clear()
        self._imd_history.clear()
        self._spectrum_history.clear()

    def _apply_result_averaging(self, results: dict) -> dict:
        """Apply moving average to harmonic metrics using raw components."""
        count = self.average_count
        if count <= 1:
            self.reset_averaging_state()
            # Check for invalid THD even without averaging
            thdn_pct = results.get("thdn_percent", 0.0)
            thd_pct = results.get("thd_percent", 0.0)
            results["thd_valid"] = True
            if thdn_pct < thd_pct:
                results["thd_valid"] = False
            return results

        raw_fund_rms = float(results.get("raw_fund_rms", 0.0))
        raw_res_rms = float(results.get("raw_res_rms", 0.0))
        raw_fund_amp = float(results.get("raw_fund_amp", 0.0))
        raw_freq = float(results.get("basic_wave", {}).get("frequency", self.gen_frequency))
        raw_amp_dbfs = float(results.get("basic_wave", {}).get("amplitude_dbfs", -140.0))
        raw_harmonics = np.array(results.get("raw_harmonics", []), dtype=float)

        # Store current state
        current_state = {
            "fund_rms": raw_fund_rms,
            "res_rms": raw_res_rms,
            "fund_amp": raw_fund_amp,
            "frequency": raw_freq,
            "target_frequency": results.get("basic_wave", {}).get("target_frequency", raw_freq),
            "amplitude_dbfs": raw_amp_dbfs,
            "harmonics": raw_harmonics,
        }

        self._result_history.append(current_state)
        while len(self._result_history) > count:
            self._result_history.popleft()

        # Compute average
        avg_state = {}
        history_len = len(self._result_history)

        # We need to average scalars and arrays
        # Initialize with zeros
        avg_state["fund_rms"] = 0.0
        avg_state["res_rms"] = 0.0
        avg_state["fund_amp"] = 0.0
        avg_state["fund_amp"] = 0.0
        avg_state["frequency"] = 0.0
        avg_state["target_frequency"] = 0.0
        avg_state["amplitude_dbfs"] = 0.0
        avg_state["harmonics"] = np.zeros_like(raw_harmonics)

        for state in self._result_history:
            avg_state["fund_rms"] += state["fund_rms"]
            avg_state["res_rms"] += state["res_rms"]
            avg_state["fund_amp"] += state["fund_amp"]
            avg_state["frequency"] += state["frequency"]
            avg_state["target_frequency"] += state.get("target_frequency", state["frequency"])
            avg_state["amplitude_dbfs"] += state["amplitude_dbfs"]
            # Handle potential shape mismatch (if settings changed mid-stream, though reset should prevent it)
            if state["harmonics"].shape == avg_state["harmonics"].shape:
                avg_state["harmonics"] += state["harmonics"]

        # Divide by count
        for key in avg_state:
            avg_state[key] /= history_len

        fund_amp = max(avg_state["fund_amp"], 1e-12)
        fund_rms = max(avg_state["fund_rms"], 1e-12)
        res_rms = max(avg_state["res_rms"], 0.0)

        thd_linear = 0.0
        if fund_amp > 0 and avg_state["harmonics"].size:
            thd_linear = np.sqrt(np.sum(avg_state["harmonics"] ** 2)) / fund_amp

        thd_percent = thd_linear * 100
        thd_db = 20 * np.log10(thd_linear + 1e-12)

        thdn_linear = res_rms / fund_rms if fund_rms > 0 else 0.0
        thdn_percent = thdn_linear * 100
        thdn_db = 20 * np.log10(thdn_linear + 1e-12)
        sinad_db = -thdn_db

        # Check for invalid THD (THD+N must be >= THD)
        # We allow a small epsilon for floating point jitter if needed, but strictly:
        # If THD+N < THD, it implies noise is negative, which is impossible.
        # This usually happens when the noise floor is extremely low and algorithm artifacts dominate.
        thd_valid = True
        if thdn_linear < thd_linear:
            thd_valid = False

        # Rebuild harmonics list using averaged fundamentals for relative levels
        harmonics = []
        base_freq = avg_state["frequency"]
        for idx, amp in enumerate(avg_state["harmonics"]):
            order = idx + 2
            rel_amp = amp / fund_amp if fund_amp > 0 else 0.0
            harmonics.append(
                {
                    "order": order,
                    "frequency": base_freq * order,
                    "amplitude_dbr": 20 * np.log10(rel_amp + 1e-12),
                    "amplitude_linear": float(amp),
                }
            )

        averaged = {
            "basic_wave": {
                "frequency": avg_state["frequency"],
                "target_frequency": avg_state["target_frequency"],
                "amplitude_dbfs": avg_state["amplitude_dbfs"],
                "max_amplitude": avg_state["fund_amp"],
            },
            "harmonics": harmonics,
            "thd_percent": thd_percent,
            "thd_db": thd_db,
            "thdn_percent": thdn_percent,
            "thdn_db": thdn_db,
            "sinad_db": sinad_db,
            # Preserve averaged raw components for downstream use/inspection
            "raw_fund_rms": avg_state["fund_rms"],
            "raw_res_rms": avg_state["res_rms"],
            "raw_harmonics": avg_state["harmonics"],
            "raw_fund_amp": avg_state["fund_amp"],
            "fft_data": results.get("fft_data"),
            "thd_valid": thd_valid,
        }

        return averaged

    def _apply_imd_averaging(self, imd_result: dict) -> dict:
        """Apply moving average to IMD results in the linear domain."""
        count = self.average_count
        if count <= 1:
            self._imd_history.clear()
            return imd_result

        raw_ratio = max(float(imd_result.get("imd", 0.0)) / 100.0, 0.0)

        self._imd_history.append(raw_ratio)
        while len(self._imd_history) > count:
            self._imd_history.popleft()

        ratio = sum(self._imd_history) / len(self._imd_history)

        imd_percent = ratio * 100.0
        imd_db = 20 * np.log10(ratio) if ratio > 1e-12 else -100.0

        return {"imd": imd_percent, "imd_db": imd_db, "raw_imd_ratio": ratio}

    def apply_spectrum_averaging(self, mag_linear: np.ndarray) -> np.ndarray:
        """Smooth spectrum magnitude with moving average (linear domain)."""
        count = self.average_count
        if count <= 1:
            self._spectrum_history.clear()
            return mag_linear

        self._spectrum_history.append(mag_linear)
        while len(self._spectrum_history) > count:
            self._spectrum_history.popleft()

        # Compute average
        # Ensure all shapes match (should be consistent if buffer size doesn't change)
        if not self._spectrum_history:
             return mag_linear

        # Simple mean
        # Stack and mean allows for fast computation
        # But deque contains arrays, so:
        current_len = len(self._spectrum_history)
        avg_spectrum = sum(self._spectrum_history) / current_len

        return avg_spectrum

    @property
    def gen_amplitude(self):
        return self._gen_amplitude

    @gen_amplitude.setter
    def gen_amplitude(self, value):
        # Clamp to prevent overflow (e.g. if user enters Hz in dB field)
        # Max 10.0 (20dB headroom above 0dBFS) is plenty.
        if value > 10.0:
            value = 10.0
        elif value < 0.0:
            value = 0.0
        self._gen_amplitude = value

    @property
    def name(self) -> str:
        return "Distortion Analyzer"

    @property
    def description(self) -> str:
        return "THD, THD+N, and SINAD measurements."

    def get_widget(self):
        return DistortionAnalyzerWidget(self)

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self.reset_averaging_state()
        self.input_data = np.zeros(self.buffer_size)
        self.current_result = None

        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            # Generate Signal
            outdata.fill(0)
            if self.output_enabled:
                # Check signal type
                if self.signal_type == "smpte" or self.signal_type == "ccif":
                    sine_wave = self._generate_dual_tone(frames, sample_rate)
                else:
                    # Phase Accumulator Logic for continuity
                    phase_inc = 2 * np.pi * self.gen_frequency / sample_rate
                    phases = self._phase_accumulator + phase_inc * (np.arange(frames) + 1)
                    phases %= (2 * np.pi)
                    self._phase_accumulator = phases[-1]
                    sine_wave = self.gen_amplitude * np.sin(phases)

                if self.output_channel == 0:
                    outdata[:, 0] = sine_wave
                elif self.output_channel == 1:
                    if outdata.shape[1] > 1:
                        outdata[:, 1] = sine_wave
            else:
                pass

            # Capture Input
            capture_ch = self.input_channel

            if indata.shape[1] > capture_ch:
                new_data = indata[:, capture_ch]
            else:
                new_data = indata[:, 0]

            # Ring buffer update
            if len(new_data) > self.buffer_size:
                self.input_data[:] = new_data[-self.buffer_size :]
            else:
                self.input_data = np.roll(self.input_data, -len(new_data))
                self.input_data[-len(new_data) :] = new_data

            # Handle Capture Request (Thread-safe copy)
            if self.capture_requested:
                self.captured_buffer = self.input_data.copy()
                self.capture_requested = False
                self.capture_ready = True

        self.callback_id = self.audio_engine.register_callback(callback)

    def _generate_dual_tone(self, frames, sample_rate):
        # Calculate amplitudes based on ratio
        # Total amplitude should not exceed self.gen_amplitude

        if self.imd_standard == "smpte":
            # ratio = amp_f1 / amp_f2
            # amp_f2 * (ratio + 1) = self.gen_amplitude
            amp_f2 = self.gen_amplitude / (self.imd_ratio + 1)
            amp_f1 = amp_f2 * self.imd_ratio
        else:  # CCIF
            # 1:1 ratio usually
            amp_f1 = self.gen_amplitude / 2
            amp_f2 = self.gen_amplitude / 2

        # Generate phases
        phase_inc_f1 = 2 * np.pi * self.imd_f1 / sample_rate
        phase_inc_f2 = 2 * np.pi * self.imd_f2 / sample_rate

        t = np.arange(frames)
        phases_f1 = self._phase_f1 + t * phase_inc_f1
        phases_f2 = self._phase_f2 + t * phase_inc_f2

        # Update state
        self._phase_f1 = (self._phase_f1 + frames * phase_inc_f1) % (2 * np.pi)
        self._phase_f2 = (self._phase_f2 + frames * phase_inc_f2) % (2 * np.pi)

        signal = amp_f1 * np.sin(phases_f1) + amp_f2 * np.sin(phases_f2)
        return signal

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def request_capture(self):
        """Request a thread-safe capture of the current input buffer."""
        self.capture_ready = False
        self.capture_requested = True


class SweepWorker(QThread):
    result_ready = pyqtSignal(dict)
    finished = pyqtSignal()
    progress = pyqtSignal(int, int)

    def __init__(self, module, sweep_type, start, end, steps, duration_ms=1000):
        super().__init__()
        self.module = module
        self.sweep_type = sweep_type  # 'frequency' or 'amplitude'
        self.start_val = start
        self.end_val = end
        self.steps = steps
        self.duration_ms = duration_ms
        self.is_running = True

    def run(self):
        # Generate steps
        if self.sweep_type == "frequency":
            # Logarithmic sweep for frequency
            values = np.logspace(np.log10(self.start_val), np.log10(self.end_val), self.steps)
        else:
            # Linear sweep for amplitude (dB)
            values = np.linspace(self.start_val, self.end_val, self.steps)

        for i, val in enumerate(values):
            if not self.is_running:
                break

            # Set Generator
            if self.sweep_type == "frequency":
                if self.module.snap_to_bin_center:
                    sample_rate = self.module.audio_engine.sample_rate
                    bin_width = sample_rate / self.module.buffer_size
                    # Snap to nearest bin
                    bin_idx = round(val / bin_width)
                    actual_freq = bin_idx * bin_width
                    if actual_freq <= 0:
                        actual_freq = bin_width  # Avoid DC
                    self.module.gen_frequency = actual_freq
                    # We store the target value for the plot X axis, but generate the actual frequency
                else:
                    self.module.gen_frequency = val
            else:
                # val is dBFS, convert to linear
                self.module.gen_amplitude = 10 ** (val / 20)

            # Wait for settling (Generator update + Audio Buffer Latency)
            # Ensure at least 300ms wait
            wait_time = max(300, self.duration_ms)
            self.msleep(wait_time)

            self.module.reset_averaging_state()
            avg_count = max(1, self.module.average_count)
            final_result = None
            results = None

            for _ in range(avg_count):
                if not self.is_running:
                    break

                # Use safe capture
                self.module.request_capture()
                # Wait for capture
                timeout = 0
                while not self.module.capture_ready and timeout < 50:  # 500ms timeout
                    self.msleep(10)
                    timeout += 1

                if self.module.capture_ready:
                    data = self.module.captured_buffer
                else:
                    data = self.module.input_data.copy()  # Fallback

                sample_rate = self.module.audio_engine.sample_rate

                # In sweep mode, gen_frequency is already set to the actual frequency (snapped or not)
                # But we want to preserve the sweep parameter 'val' as the target
                results = AudioCalc.analyze_harmonics(data, self.module.gen_frequency, self.module.window_type, sample_rate)

                # Add target frequency to results if we are snapping
                if self.module.snap_to_bin_center and self.sweep_type == "frequency":
                     results["basic_wave"]["target_frequency"] = val
                else:
                     results["basic_wave"]["target_frequency"] = self.module.gen_frequency

                final_result = self.module._apply_result_averaging(results)

            if results is None:
                continue

            if final_result:
                results = final_result

            # Add sweep parameter to results
            results["sweep_param"] = val
            self.result_ready.emit(results)
            self.progress.emit(i + 1, self.steps)

        self.finished.emit()

    def stop(self):
        self.is_running = False


class RealtimeAnalysisWorker(QObject):
    result_ready = pyqtSignal(dict)

    def process(self, data, settings):
        try:
            signal_type = settings.get("signal_type", "sine")
            sample_rate = settings.get("sample_rate", 48000)
            window_type = settings.get("window_type", "blackmanharris")

            if signal_type in ["smpte", "ccif"]:
                window = get_cached_window(window_type, len(data), dtype=data.dtype)
                fft_data = fft_manager.rfft(data * window)
                mag_linear = np.abs(fft_data) * (2 / np.sum(window))
                freqs = fft_manager.rfftfreq(len(data), 1 / sample_rate)

                imd_f1 = settings.get("imd_f1", 60.0)
                imd_f2 = settings.get("imd_f2", 7000.0)

                if signal_type == "smpte":
                    res = AudioCalc.calculate_imd_smpte(mag_linear, freqs, imd_f1, imd_f2)
                else:
                    res = AudioCalc.calculate_imd_ccif(mag_linear, freqs, imd_f1, imd_f2)

                # Add type and data for UI
                res["type"] = "imd"
                res["fft_data"] = fft_data
                res["mag_linear"] = mag_linear  # Pass linear mag for averaging
                res["input_rms_db"] = 20 * np.log10(np.sqrt(np.mean(data**2)) + 1e-12)

                self.result_ready.emit(res)
            else:
                gen_frequency = settings.get("gen_frequency", 1000.0)
                # target_frequency logic could be passed in settings, 
                # but for real-time mode we rely on what was set in module.
                # However, the worker processes a snapshot of settings.
                # Let's pass target vs actual in settings

                target_freq = settings.get("target_frequency", gen_frequency)

                results = AudioCalc.analyze_harmonics(data, gen_frequency, window_type, sample_rate)
                results["type"] = "harmonics"
                results["basic_wave"]["target_frequency"] = target_freq
                self.result_ready.emit(results)

        except Exception as e:
            print(f"Error in analysis worker: {e}")


class DistortionAnalyzerWidget(QWidget):
    start_analysis_signal = pyqtSignal(np.ndarray, dict)

    def __init__(self, module: DistortionAnalyzer):
        super().__init__()
        self.module = module
        self.sweep_worker = None
        self.init_ui()

        # Worker Thread Setup
        self.analysis_thread = QThread()
        self.worker = RealtimeAnalysisWorker()
        self.worker.moveToThread(self.analysis_thread)
        self.start_analysis_signal.connect(self.worker.process)
        self.worker.result_ready.connect(self.on_worker_result)
        self.analysis_thread.start()

        self.analysis_pending = False

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_realtime_analysis)
        self.timer.setInterval(100)  # 10Hz update

    def init_ui(self):
        layout = QHBoxLayout()

        # --- Left Panel: Controls & Meters ---
        left_panel = QVBoxLayout()
        left_panel.setSpacing(10)

        # 1. Mode Selection
        mode_group = QGroupBox(tr("Mode"))
        mode_layout = QVBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([tr("Real-time"), tr("Frequency Sweep"), tr("Amplitude Sweep")])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_group.setLayout(mode_layout)
        left_panel.addWidget(mode_group)

        # 2. Settings Tabs
        self.settings_tabs = QTabWidget()

        # Page 1: Real-time Controls
        rt_widget = QWidget()
        rt_layout = QFormLayout()

        # Output Mode
        self.out_mode_combo = QComboBox()
        self.out_mode_combo.addItems([tr("Off (External Source)"), tr("Sine Wave"), tr("SMPTE IMD"), tr("CCIF IMD")])
        self.out_mode_combo.currentIndexChanged.connect(self.on_out_mode_changed)
        rt_layout.addRow(tr("Signal Generator:"), self.out_mode_combo)

        # Generator Settings Stack
        self.gen_stack = QStackedWidget()

        # 1. Sine Settings
        sine_widget = QWidget()
        sine_layout = QFormLayout()
        sine_layout.setContentsMargins(0, 0, 0, 0)

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(1000)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(self.on_freq_changed)
        sine_layout.addRow(tr("Frequency:"), self.freq_spin)

        # Bin Snapping
        self.snap_check = QPushButton(tr("Bin Center"))
        self.snap_check.setCheckable(True)
        self.snap_check.toggled.connect(self.on_snap_changed)
        sine_layout.addRow(tr("Snap to Bin:"), self.snap_check)

        # Actual Frequency Display
        self.actual_freq_label = QLabel("--- Hz")
        self.actual_freq_label.setStyleSheet("color: #aaaaaa;")
        sine_layout.addRow(tr("Actual Freq:"), self.actual_freq_label)

        sine_widget.setLayout(sine_layout)
        self.gen_stack.addWidget(sine_widget)

        # 2. IMD Settings
        imd_gen_widget = QWidget()
        imd_gen_layout = QFormLayout()
        imd_gen_layout.setContentsMargins(0, 0, 0, 0)

        self.imd_f1_spin = QDoubleSpinBox()
        self.imd_f1_spin.setRange(10, 20000)
        self.imd_f1_spin.setValue(self.module.imd_f1)
        self.imd_f1_spin.valueChanged.connect(lambda v: setattr(self.module, "imd_f1", v))
        imd_gen_layout.addRow(tr("Freq 1 (Hz):"), self.imd_f1_spin)

        self.imd_f2_spin = QDoubleSpinBox()
        self.imd_f2_spin.setRange(10, 24000)
        self.imd_f2_spin.setValue(self.module.imd_f2)
        self.imd_f2_spin.valueChanged.connect(lambda v: setattr(self.module, "imd_f2", v))
        imd_gen_layout.addRow(tr("Freq 2 (Hz):"), self.imd_f2_spin)

        self.imd_ratio_spin = QDoubleSpinBox()
        self.imd_ratio_spin.setRange(1, 10)
        self.imd_ratio_spin.setValue(self.module.imd_ratio)
        self.imd_ratio_spin.valueChanged.connect(lambda v: setattr(self.module, "imd_ratio", v))
        imd_gen_layout.addRow(tr("Ratio (F1:F2):"), self.imd_ratio_spin)

        imd_gen_widget.setLayout(imd_gen_layout)
        self.gen_stack.addWidget(imd_gen_widget)

        rt_layout.addRow(self.gen_stack)

        # Amplitude (Shared)
        amp_layout = QHBoxLayout()
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-120, 20)  # Allow positive for dBV/dBu
        self.amp_spin.setValue(-6)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dBFS", "dBV", "dBu", "Vrms"])
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)

        amp_layout.addWidget(self.amp_spin)
        amp_layout.addWidget(self.unit_combo)
        rt_layout.addRow(tr("Amplitude:"), amp_layout)

        rt_widget.setLayout(rt_layout)
        self.settings_tabs.addTab(rt_widget, tr("Signal"))

        # Page 2: Sweep Controls
        sweep_widget = QWidget()
        sweep_layout = QFormLayout()

        self.sweep_start_spin = QDoubleSpinBox()
        self.sweep_start_spin.setRange(-120, 20000)
        self.sweep_start_spin.setValue(20)
        sweep_layout.addRow(tr("Start:"), self.sweep_start_spin)

        self.sweep_end_spin = QDoubleSpinBox()
        self.sweep_end_spin.setRange(-120, 20000)
        self.sweep_end_spin.setValue(20000)
        sweep_layout.addRow(tr("End:"), self.sweep_end_spin)

        self.sweep_steps_spin = QSpinBox()
        self.sweep_steps_spin.setRange(2, 1000)
        self.sweep_steps_spin.setValue(30)
        sweep_layout.addRow(tr("Steps:"), self.sweep_steps_spin)

        sweep_widget.setLayout(sweep_layout)
        self.settings_tabs.addTab(sweep_widget, tr("Sweep"))

        # Settings Tab
        common_widget = QWidget()
        common_layout = QFormLayout()

        self.in_channel_combo = QComboBox()
        self.in_channel_combo.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)")])
        self.in_channel_combo.currentIndexChanged.connect(self.on_in_channel_changed)
        common_layout.addRow(tr("Input Ch:"), self.in_channel_combo)

        self.channel_combo = QComboBox()
        self.channel_combo.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)")])
        self.channel_combo.currentIndexChanged.connect(self.on_channel_changed)
        common_layout.addRow(tr("Output Ch:"), self.channel_combo)

        # Averaging (Count)
        self.avg_label = QLabel(tr("Avg Count:"))
        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 128)
        self.avg_spin.setValue(1)
        self.avg_spin.setFixedWidth(80)
        self.avg_spin.valueChanged.connect(self.on_avg_changed)

        avg_row = QHBoxLayout()
        avg_row.addWidget(self.avg_label)
        avg_row.addWidget(self.avg_spin)
        common_layout.addRow(tr("Averaging:"), avg_row)

        common_widget.setLayout(common_layout)
        self.settings_tabs.addTab(common_widget, tr("Settings"))

        left_panel.addWidget(self.settings_tabs)

        # Action Buttons
        btn_layout = QVBoxLayout()
        self.action_btn = QPushButton(tr("Start Measurement"))
        self.action_btn.setCheckable(True)
        self.action_btn.clicked.connect(self.on_action)
        self.action_btn.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        btn_layout.addWidget(self.action_btn)

        left_panel.addLayout(btn_layout)

        # 3. Meters (Real-time only)
        self.meters_group = QGroupBox(tr("Measurements"))
        self.meters_main_layout = QVBoxLayout()
        self.meters_group.setLayout(self.meters_main_layout)

        # View switcher
        self.meters_view_stack = QStackedWidget()
        self.meters_main_layout.addWidget(self.meters_view_stack)

        # --- Basic View ---
        basic_view = QWidget()
        meters_layout = QFormLayout(basic_view)

        # THD+N row (value and dB on one line)
        thdn_row = QWidget()
        thdn_row_layout = QHBoxLayout(thdn_row)
        thdn_row_layout.setContentsMargins(0, 0, 0, 0)
        self.thdn_label = QLabel(tr("-- %"))
        self.thdn_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ff5555;")
        self.thdn_db_label = QLabel(tr("-- dB"))
        thdn_row_layout.addWidget(self.thdn_label)
        thdn_row_layout.addWidget(self.thdn_db_label)
        thdn_row_layout.addStretch()
        meters_layout.addRow(QLabel(tr("THD+N:")), thdn_row)

        # THD row
        self.thd_label = QLabel(tr("-- %"))
        self.thd_label.setStyleSheet("font-size: 16px; color: #ffaa55;")
        meters_layout.addRow(QLabel(tr("THD:")), self.thd_label)

        # SINAD row
        self.sinad_label = QLabel(tr("-- dB"))
        self.sinad_label.setStyleSheet("font-size: 16px; color: #55ffff;")
        meters_layout.addRow(QLabel(tr("SINAD:")), self.sinad_label)

        # IMD row (Hidden by default)
        self.imd_label = QLabel(tr("-- %"))
        self.imd_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ff55ff;")
        self.imd_db_label = QLabel(tr("-- dB"))
        self.imd_row_widget = QWidget()
        imd_row_layout = QHBoxLayout(self.imd_row_widget)
        imd_row_layout.setContentsMargins(0, 0, 0, 0)
        imd_row_layout.addWidget(self.imd_label)
        imd_row_layout.addWidget(self.imd_db_label)
        imd_row_layout.addStretch()
        meters_layout.addRow(QLabel(tr("IMD:")), self.imd_row_widget)
        self.imd_row_widget.setVisible(False)

        self.meters_view_stack.addWidget(basic_view)

        # --- Detailed View ---
        detailed_view = QWidget()
        detailed_layout = QVBoxLayout(detailed_view)
        detailed_layout.setContentsMargins(0, 5, 0, 5)

        self.detailed_label = QLabel()
        self.detailed_label.setStyleSheet("font-family: 'Courier New', monospace; font-size: 14px; line-height: 1.5;")
        self.detailed_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        detailed_layout.addWidget(self.detailed_label)

        self.meters_view_stack.addWidget(detailed_view)

        # Toggle button
        self.view_toggle_btn = QPushButton(tr("Show Detailed"))
        self.view_toggle_btn.setCheckable(True)
        self.view_toggle_btn.clicked.connect(self.on_toggle_view)
        self.meters_main_layout.addWidget(self.view_toggle_btn)

        left_panel.addWidget(self.meters_group)

        left_panel.addStretch()
        layout.addLayout(left_panel, 1)

        # --- Right Panel: Plots & Tables ---
        right_panel = QVBoxLayout()

        self.tabs = QTabWidget()

        # Tab 1: Spectrum
        self.spectrum_plot = pg.PlotWidget()
        self.spectrum_plot.setLabel("left", tr("Amplitude"), units="dBFS")
        self.spectrum_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.spectrum_plot.setLogMode(x=True, y=False)
        self.spectrum_plot.setYRange(-140, 0)
        self.spectrum_plot.setYRange(-140, 0)
        self.spectrum_plot.showGrid(x=True, y=True)

        # Custom Axis Ticks for Spectrum
        axis_spec = self.spectrum_plot.getPlotItem().getAxis("bottom")
        ticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        ticks_log = [(np.log10(t), str(t) if t < 1000 else f"{t / 1000:.0f}k") for t in ticks]
        axis_spec.setTicks([ticks_log])

        # Set Range (log domain)
        self.spectrum_plot.setXRange(np.log10(20), np.log10(20000))

        self.spectrum_curve = self.spectrum_plot.plot(pen="y")
        self.tabs.addTab(self.spectrum_plot, tr("Spectrum"))

        # Tab 2: Harmonics (Table + Bar Graph)
        harmonics_widget = QWidget()
        harmonics_layout = QVBoxLayout(harmonics_widget)

        self.harmonics_table = QTableWidget()
        self.harmonics_table.setColumnCount(4)
        self.harmonics_table.setHorizontalHeaderLabels(
            [tr("Order"), tr("Freq (Hz)"), tr("Level (dBr)"), tr("Level (Linear)")]
        )
        self.harmonics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        harmonics_layout.addWidget(self.harmonics_table, 1)  # Stretch factor 1

        # Harmonics Bar Graph
        self.harmonics_plot = pg.PlotWidget()
        self.harmonics_plot.setLabel("left", tr("Level"), units="dBr")
        self.harmonics_plot.setLabel("bottom", tr("Harmonic Order"))
        self.harmonics_plot.showGrid(x=False, y=True)
        self.harmonics_plot.setYRange(-140, 0)

        self.harmonics_bar_item = pg.BarGraphItem(x=[], height=[], width=0.6, brush="b")
        self.harmonics_plot.addItem(self.harmonics_bar_item)

        harmonics_layout.addWidget(self.harmonics_plot, 1)  # Stretch factor 1

        self.tabs.addTab(harmonics_widget, tr("Harmonics"))

        # Tab 3: Sweep Results
        self.sweep_plot = pg.PlotWidget()
        self.sweep_plot.setLabel("left", tr("THD+N"), units="dB")
        self.sweep_plot.setLabel("bottom", tr("Frequency"), units="Hz")  # Dynamic label
        self.sweep_plot.setLogMode(x=True, y=False)
        self.sweep_plot.setYRange(-140, 0)
        self.sweep_plot.showGrid(x=True, y=True)

        # Custom Axis Ticks for Sweep (Frequency Mode)
        # Note: If mode changes to Amplitude Sweep, we might need to reset this?
        # The user only requested "like Spectrum Analyzer", which implies Frequency domain.
        # We'll set it here, and handle mode changes if necessary.
        self.sweep_axis = self.sweep_plot.getPlotItem().getAxis("bottom")
        self.sweep_axis.setTicks([ticks_log])

        # Set Range (log domain) for Frequency Sweep default
        self.sweep_plot.setXRange(np.log10(20), np.log10(20000))

        self.sweep_curve = self.sweep_plot.plot(pen="c")
        self.tabs.addTab(self.sweep_plot, tr("Sweep Results"))

        right_panel.addWidget(self.tabs)
        layout.addLayout(right_panel, 3)

        # Initial update of Actual Frequency
        self.update_actual_frequency()

        self.setLayout(layout)

        # Initial update
        self.on_unit_changed(self.unit_combo.currentText())
        self.out_mode_combo.setCurrentIndex(1)  # Default to Sine Wave

    def sync_module_with_gui(self):
        """Synchronize the measurement module state with current GUI values."""
        # 1. Generator Settings
        # Update frequency based on snap setting
        self.on_freq_changed(self.freq_spin.value())
        self.module.gen_amplitude = self.get_linear_amplitude()
        self.module.snap_to_bin_center = self.snap_check.isChecked()

        # 2. Signal Type (from out_mode_combo)
        out_idx = self.out_mode_combo.currentIndex()
        if out_idx == 0:
            self.module.output_enabled = False
        else:
            self.module.output_enabled = True
            if out_idx == 1:
                self.module.signal_type = "sine"
            elif out_idx == 2:
                self.module.signal_type = "smpte"
                self.module.imd_standard = "smpte"
            elif out_idx == 3:
                self.module.signal_type = "ccif"
                self.module.imd_standard = "ccif"

        # 3. IMD Settings
        self.module.imd_f1 = self.imd_f1_spin.value()
        self.module.imd_f2 = self.imd_f2_spin.value()
        self.module.imd_ratio = self.imd_ratio_spin.value()

        # 4. IO Channels
        self.module.input_channel = self.in_channel_combo.currentIndex()
        self.module.output_channel = self.channel_combo.currentIndex()

        # 5. Averaging
        self.module.average_count = self.avg_spin.value()

        self.module.reset_averaging_state()

    def on_mode_changed(self, idx):
        # 0: Real-time, 1: Frequency Sweep, 2: Amplitude Sweep
        modes = ["Real-time", "Frequency Sweep", "Amplitude Sweep"]
        if 0 <= idx < len(modes):
            self.module.mode = modes[idx]

        # Reset sweep data and plot when changing from/to sweep modes
        self.module.sweep_results = []
        self.sweep_curve.setData([], [])

        if idx == 0:  # Real-time
            self.settings_tabs.setCurrentIndex(0)
            self.meters_group.setVisible(True)
            self.set_meters_mode("thd")
            self.tabs.setCurrentIndex(0)
            self.sync_module_with_gui()
        else:
            self.settings_tabs.setCurrentIndex(1)
            self.meters_group.setVisible(False)
            self.tabs.setCurrentIndex(2)

            if idx == 1:  # Frequency Sweep
                self.sweep_start_spin.setSuffix(" Hz")
                self.sweep_end_spin.setSuffix(" Hz")
                self.sweep_start_spin.setValue(20)
                self.sweep_end_spin.setValue(20000)
                self.sweep_plot.setLabel("bottom", tr("Frequency"), units="Hz")
                self.sweep_plot.setLogMode(x=True, y=False)
                # Restore custom ticks for frequency
                ticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
                ticks_log = [(np.log10(t), str(t) if t < 1000 else f"{t / 1000:.0f}k") for t in ticks]
                self.sweep_axis.setTicks([ticks_log])
                self.sweep_plot.setXRange(np.log10(20), np.log10(20000))
            else:  # Amplitude Sweep
                self.sweep_start_spin.setSuffix(" dBFS")
                self.sweep_end_spin.setSuffix(" dBFS")
                self.sweep_start_spin.setValue(-60)
                self.sweep_end_spin.setValue(0)
                self.sweep_plot.setLabel("bottom", tr("Amplitude"), units="dBFS")
                self.sweep_plot.setLogMode(x=False, y=False)
                # Reset ticks to auto for amplitude
                self.sweep_axis.setTicks(None)
                # X-axis matches initial measurement range, fixed Y-axis
                self.sweep_plot.setXRange(-60, 0)
                self.sweep_plot.setYRange(-140, 0)

    def on_out_mode_changed(self, idx):
        # 0: Off, 1: Sine, 2: SMPTE, 3: CCIF
        if idx == 0:  # Off
            self.module.output_enabled = False
            self.gen_stack.setVisible(False)
            self.amp_spin.setEnabled(False)
            self.unit_combo.setEnabled(False)
            self.module.signal_type = "sine"  # Default
        else:
            self.module.output_enabled = True
            self.gen_stack.setVisible(True)
            self.amp_spin.setEnabled(True)
            self.unit_combo.setEnabled(True)

            if idx == 1:  # Sine
                self.module.signal_type = "sine"
                self.gen_stack.setCurrentIndex(0)
                self.set_meters_mode("thd")
                self.module.reset_averaging_state()
            elif idx == 2:  # SMPTE
                self.module.signal_type = "smpte"
                self.module.imd_standard = "smpte"
                self.gen_stack.setCurrentIndex(1)
                self.set_meters_mode("imd")
                # Update IMD params
                self.module.imd_f1 = 60.0
                self.module.imd_f2 = 7000.0
                self.imd_f1_spin.setValue(60.0)
                self.imd_f2_spin.setValue(7000.0)
                self.imd_ratio_spin.setEnabled(True)
                self.module.reset_averaging_state()
            elif idx == 3:  # CCIF
                self.module.signal_type = "ccif"
                self.module.imd_standard = "ccif"
                self.gen_stack.setCurrentIndex(1)
                self.set_meters_mode("imd")
                # Update IMD params
                self.module.imd_f1 = 19000.0
                self.module.imd_f2 = 20000.0
                self.imd_f1_spin.setValue(19000.0)
                self.imd_f2_spin.setValue(20000.0)
                self.imd_ratio_spin.setEnabled(False)
                self.module.reset_averaging_state()

    def on_unit_changed(self, unit):
        # Update spin box range/value based on current amplitude
        # Current amplitude is stored in module as Linear (0-1)
        # But we need to convert it.
        # Actually, let's just update the display value.

        amp_linear = self.module.gen_amplitude
        gain = self.module.audio_engine.calibration.output_gain

        self.amp_spin.blockSignals(True)

        if unit == "dBFS":
            val = 20 * np.log10(amp_linear + 1e-12)
        elif unit == "dBV":
            v_peak = amp_linear * gain
            v_rms = v_peak / np.sqrt(2)
            val = 20 * np.log10(v_rms + 1e-12)
        elif unit == "dBu":
            v_peak = amp_linear * gain
            v_rms = v_peak / np.sqrt(2)
            val = 20 * np.log10((v_rms + 1e-12) / 0.7746)
        elif unit == "Vrms":
            v_peak = amp_linear * gain
            val = v_peak / np.sqrt(2)

        self.amp_spin.setValue(val)
        self.amp_spin.blockSignals(False)

        self.amp_spin.setValue(val)
        self.amp_spin.blockSignals(False)

    def get_linear_amplitude(self):
        val = self.amp_spin.value()
        unit = self.unit_combo.currentText()
        gain = self.module.audio_engine.calibration.output_gain
        amp_linear = 0.0

        if unit == "dBFS":
            amp_linear = 10 ** (val / 20)
        elif unit == "dBV":
            v_rms = 10 ** (val / 20)
            v_peak = v_rms * np.sqrt(2)
            amp_linear = v_peak / gain
        elif unit == "dBu":
            v_rms = 0.7746 * 10 ** (val / 20)
            v_peak = v_rms * np.sqrt(2)
            amp_linear = v_peak / gain
        elif unit == "Vrms":
            v_peak = val * np.sqrt(2)
            amp_linear = v_peak / gain

        # Clamp
        if amp_linear > 1.0:
            amp_linear = 1.0
        elif amp_linear < 0.0:
            amp_linear = 0.0

        return amp_linear

    def on_amp_changed(self, val):
        self.module.gen_amplitude = self.get_linear_amplitude()
        self.module.reset_averaging_state()

    def on_action(self, checked):
        idx = self.mode_combo.currentIndex()
        if idx == 0:  # Real-time
            self.on_toggle_realtime(checked)
        else:
            if checked:
                self.start_sweep(idx)
            else:
                self.stop_sweep()

    def on_toggle_realtime(self, checked):
        if checked:
            self.mode_combo.setEnabled(False)
            self.sync_module_with_gui()
            self.module.start_analysis()
            self.timer.start()
            self.action_btn.setText(tr("Stop Measurement"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.action_btn.setText(tr("Start Measurement"))
            self.mode_combo.setEnabled(True)

    def set_meters_mode(self, mode):
        if mode == "thd":
            self.thdn_label.setVisible(True)
            self.thdn_db_label.setVisible(True)
            self.thd_label.setVisible(True)
            self.sinad_label.setVisible(True)
            self.imd_row_widget.setVisible(False)

        else:  # imd
            self.thdn_label.setVisible(False)
            self.thdn_db_label.setVisible(False)
            self.thd_label.setVisible(False)
            self.sinad_label.setVisible(False)
            self.imd_row_widget.setVisible(True)

    def start_sweep(self, mode_idx):
        self.module.start_analysis()  # Ensure audio is running
        self.action_btn.setText(tr("Stop Sweep"))
        self.module.sweep_results = []
        self.sweep_curve.setData([], [])

        sweep_type = "frequency" if mode_idx == 1 else "amplitude"
        start = self.sweep_start_spin.value()
        end = self.sweep_end_spin.value()
        steps = self.sweep_steps_spin.value()

        # Update plot range to match measurement settings
        if sweep_type == "frequency":
            if start > 0 and end > 0:
                self.sweep_plot.setXRange(np.log10(start), np.log10(end))
        else:
            self.sweep_plot.setXRange(start, end)
        self.sweep_plot.setYRange(-140, 0)

        if sweep_type == "frequency":
            if start <= 0 or end <= 0:
                print("Error: Frequency sweep range must be positive.")
                self.action_btn.setChecked(False)
                self.action_btn.setText(tr("Start Measurement"))
                return

        self.mode_combo.setEnabled(False)
        self.sweep_worker = SweepWorker(self.module, sweep_type, start, end, steps)
        self.sweep_worker.result_ready.connect(self.on_sweep_result)
        self.sweep_worker.finished.connect(self.on_sweep_finished)
        self.sweep_worker.start()

    def stop_sweep(self):
        if self.sweep_worker:
            self.sweep_worker.stop()
            self.sweep_worker.wait()
            self.sweep_worker = None
        self.module.stop_analysis()
        self.sync_module_with_gui()  # Restore manual settings
        self.action_btn.setText(tr("Start Measurement"))
        self.action_btn.setChecked(False)
        self.mode_combo.setEnabled(True)

    def on_toggle_view(self, checked):
        if checked:
            self.meters_view_stack.setCurrentIndex(1)
            self.view_toggle_btn.setText(tr("Show Basic"))
        else:
            self.meters_view_stack.setCurrentIndex(0)
            self.view_toggle_btn.setText(tr("Show Detailed"))

    def on_sweep_result(self, result):
        self.module.sweep_results.append(result)

        # Update Plot
        x_data = [r["sweep_param"] for r in self.module.sweep_results]
        y_data = [r["thdn_db"] for r in self.module.sweep_results]

        x_plot = np.array(x_data)

        self.sweep_curve.setSymbol("o")
        self.sweep_curve.setData(x_plot, y_data)

    def on_sweep_finished(self):
        self.stop_sweep()

    def update_actual_frequency(self):
        target_freq = self.freq_spin.value()
        if self.snap_check.isChecked():
            sample_rate = self.module.audio_engine.sample_rate
            bin_width = sample_rate / self.module.buffer_size
            bin_idx = round(target_freq / bin_width)
            actual_freq = bin_idx * bin_width
            if actual_freq <= 0:
                 actual_freq = bin_width # Prevent 0Hz
            self.actual_freq_label.setText(f"{actual_freq:.3f} Hz")
            self.module.gen_frequency = actual_freq
        else:
            self.actual_freq_label.setText(f"{target_freq:.3f} Hz")
            self.module.gen_frequency = target_freq

    def on_snap_changed(self, checked):
        self.module.snap_to_bin_center = checked
        self.update_actual_frequency()
        self.module.reset_averaging_state()

    def on_freq_changed(self, val):
        self.update_actual_frequency()
        self.module.reset_averaging_state()

    def on_channel_changed(self, idx):
        self.module.output_channel = idx
        self.module.reset_averaging_state()

    def on_in_channel_changed(self, idx):
        self.module.input_channel = idx
        self.module.reset_averaging_state()

    def on_avg_changed(self, val):
        self.module.average_count = val
        self.module.reset_averaging_state()

    def _format_percent(self, value):
        if value == 0:
            return tr("{0} %").format(f"{value:.5f}")
        order = np.floor(np.log10(abs(value)))
        prec = max(5, int(abs(order)))
        return tr("{0} %").format(f"{value:.{prec}f}")

    def update_realtime_analysis(self):
        if not self.module.is_running:
            return

        if self.analysis_pending:
            return

        data = self.module.input_data.copy()
        sample_rate = self.module.audio_engine.sample_rate

        settings = {
            "signal_type": self.module.signal_type,
            "window_type": self.module.window_type,
            "sample_rate": sample_rate,
            "gen_frequency": self.module.gen_frequency,
            "target_frequency": self.freq_spin.value(), # Pass target separately
            "imd_f1": self.module.imd_f1,
            "imd_f2": self.module.imd_f2,
        }

        self.analysis_pending = True
        self.start_analysis_signal.emit(data, settings)

    def on_worker_result(self, results):
        self.analysis_pending = False
        if not self.module.is_running:
            return

        res_type = results.get("type", "harmonics")
        sample_rate = self.module.audio_engine.sample_rate
        # Buffer length can be inferred from fft_data or mag_linear if passed, but easiest if consistent
        # For spectrum freq axis we need length.
        # fft_data length is N/2+1
        fft_data = results.get("fft_data")
        if fft_data is not None:
             n_fft = (len(fft_data) - 1) * 2
        elif results.get("mag_linear") is not None:
             n_fft = (len(results["mag_linear"]) - 1) * 2
        else:
             n_fft = self.module.buffer_size # Fallback

        if res_type == "imd":
            res = self.module._apply_imd_averaging(results)

            self.imd_label.setText(self._format_percent(res["imd"]))
            self.imd_db_label.setText(tr("{0:.3f} dB").format(res["imd_db"]))

            # Update Detailed Label for IMD
            window_name = self.module.window_type.capitalize()
            fft_size = n_fft
            input_level = results.get("input_rms_db", -140.0)

            detailed_text = (
                f"{tr('Input level:'):<15} {input_level:>10.1f} dBFS   ✔\n"
                f"{tr('Window:'):<15} {window_name:>10}\n"
                f"{tr('FFT size:'):<15} {fft_size:>10}\n"
                f"{tr('Bandwidth:'):<15} {'20 kHz':>10}\n"
                "--------------------------------\n"
                f"{tr('IMD:'):<15} {res['imd']:>10.5f} %\n"
                f"{tr('IMD (dB):'):<15} {res['imd_db']:>10.1f} dB\n"
                "--------------------------------"
            )
            self.detailed_label.setText(detailed_text)

            mag_linear = results.get("mag_linear")
            if mag_linear is not None:
                mag_linear = self.module.apply_spectrum_averaging(mag_linear)
                mag_db = 20 * np.log10(mag_linear + 1e-12)
                freqs = fft_manager.rfftfreq(n_fft, 1 / sample_rate)
                self.spectrum_curve.setData(freqs[1:], mag_db[1:])

        else:
            # Harmonics
            results = self.module._apply_result_averaging(results)
            self.module.current_result = results

            # Update Meters
            self.thdn_label.setText(self._format_percent(results["thdn_percent"]))
            self.thdn_db_label.setText(tr("{0:.3f} dB").format(results["thdn_db"]))

            if results.get("thd_valid", True):
                self.thd_label.setText(self._format_percent(results["thd_percent"]))
            else:
                self.thd_label.setText(tr("LO"))

            self.sinad_label.setText(tr("{0:.2f} dB").format(results["sinad_db"]))

            # ENOB Calculation
            sinad = results["sinad_db"]
            input_level = results["basic_wave"]["amplitude_dbfs"]

            if input_level >= -1.0:
                enob_calc = (sinad - 1.76) / 6.02
                enob_str = f"{enob_calc:>10.1f} bits   ✔"
            else:
                enob_str = f"{'--':>10} bits"

            # Update Detailed Label
            window_name = self.module.window_type.capitalize()
            fft_size = n_fft
            bandwidth = "20 kHz"

            detailed_text = (
                f"{tr('Target Freq:'):<15} {results['basic_wave'].get('target_frequency', 0):>10.3f} Hz\n"
                f"{tr('Actual Freq:'):<15} {results['basic_wave']['frequency']:>10.3f} Hz   ✔\n"
                f"{tr('Input level:'):<15} {input_level:>10.1f} dBFS   ✔\n"
                f"{tr('Window:'):<15} {window_name:>10}\n"
                f"{tr('FFT size:'):<15} {fft_size:>10}\n"
                f"{tr('Bandwidth:'):<15} {bandwidth:>10}\n"
                "--------------------------------\n"
                f"{tr('THD+N:'):<15} {results['thdn_db']:>10.1f} dB\n"
                f"{tr('SINAD:'):<15} {results['sinad_db']:>10.1f} dB\n"
                f"{tr('ENOB:'):<15} {enob_str}\n"
                "--------------------------------"
            )
            self.detailed_label.setText(detailed_text)

            # Update Harmonics Table & Bar Graph
            self.harmonics_table.setRowCount(len(results["harmonics"]))

            orders = []
            levels = []

            for i, h in enumerate(results["harmonics"]):
                texts = [
                    str(h["order"]),
                    f"{h['frequency']:.1f}",
                    f"{h['amplitude_dbr']:.2f}",
                    f"{h['amplitude_linear']:.6f}",
                ]
                for j, text in enumerate(texts):
                    item = self.harmonics_table.item(i, j)
                    if item:
                        item.setText(text)
                    else:
                        self.harmonics_table.setItem(i, j, QTableWidgetItem(text))

                orders.append(h["order"])
                levels.append(h["amplitude_dbr"])

            # Update Bar Graph
            if orders:
                floor_db = -140
                heights = [level - floor_db for level in levels]
                self.harmonics_bar_item.setOpts(x=orders, height=heights, y0=floor_db)
                self.harmonics_plot.setXRange(min(orders) - 1, max(orders) + 1)

            # Update Spectrum Plot
            if fft_data is not None:
                mag_linear = np.abs(fft_data) / n_fft * 2
                mag_linear = self.module.apply_spectrum_averaging(mag_linear)
                mag = 20 * np.log10(mag_linear + 1e-12)
                freqs = fft_manager.rfftfreq(n_fft, 1 / sample_rate)
                self.spectrum_curve.setData(freqs[1:], mag[1:])
