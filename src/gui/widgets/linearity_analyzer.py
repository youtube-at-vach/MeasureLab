import logging
import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QTabWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


def calculate_hysteresis(x_data, gain_data, directions):
    """
    Calculates the maximum hysteresis error between forward and reverse sweeps.
    Returns the maximum difference in dB, or None if no reverse sweep data is present.
    """
    if not x_data or not gain_data or not directions:
        return None

    dirs = np.array(directions)
    if "rev" not in dirs:
        return None

    x_arr = np.array(x_data)
    g_arr = np.array(gain_data)

    # Separate fwd and rev
    fwd_mask = dirs == "fwd"
    rev_mask = dirs == "rev"

    # We need to map inputs to gains for both
    # Assuming inputs are floats, exact match might be tricky if not careful,
    # but we generated them using linspace in reverse order, so they should match exactly.
    # However, float rounding can be annoying.

    x_fwd = x_arr[fwd_mask]
    g_fwd = g_arr[fwd_mask]

    x_rev = x_arr[rev_mask]
    g_rev = g_arr[rev_mask]

    # Vectorized Hysteresis Calculation
    # Round to handle floating point inaccuracies, similar to original dict approach
    xf_r = np.round(x_fwd, 6)
    xr_r = np.round(x_rev, 6)

    # 1. Prepare Forward Lookup (Last-Win Strategy)
    # Flip to use np.unique(first) as "Last"
    xf_flipped = xf_r[::-1]
    # xf_clean is sorted unique values
    xf_clean, unique_indices_flipped = np.unique(xf_flipped, return_index=True)

    if xf_clean.size > 0:
        # Extract corresponding G (Last occurrence wins)
        gf_clean = g_fwd[::-1][unique_indices_flipped]

        # 2. Process Reverse Sweep (Check-All Strategy)
        # Find which x_rev points exist in xf_clean
        idx_in_clean = np.searchsorted(xf_clean, xr_r)

        # Clamp indices to valid range for validity check
        idx_in_clean = np.clip(idx_in_clean, 0, len(xf_clean) - 1)

        # Check which ones are actual matches
        matched_mask = xf_clean[idx_in_clean] == xr_r

        if np.any(matched_mask):
            # Get corresponding gains from Fwd
            g_ref = gf_clean[idx_in_clean[matched_mask]]

            # Get gains from Rev
            g_check = g_rev[matched_mask]

            diffs = np.abs(g_check - g_ref)
            max_hyst = np.max(diffs)
            return max_hyst

    return 0.0


class LinearitySweepWorker(QThread):
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(dict)
    finished_sweep = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, module):
        super().__init__()
        self.module = module
        self.is_running = True
        self._stop_event = threading.Event()

    def wait_interruptible(self, duration: float, interval: float = 0.05):
        """Waits for `duration` seconds, checking `is_running` efficiently using an Event."""
        if not self.is_running:
            return
        self._stop_event.wait(duration)

    def run(self):
        try:
            # 1. Generate Levels (High to Low usually, or Low to High)
            # AES17 usually implies stepping down from 0 dBFS.
            start_db = self.module.start_level
            end_db = self.module.end_level
            steps = self.module.steps

            # Linear space for dB means... linspace in dB domain
            levels_db = np.linspace(start_db, end_db, steps)

            if self.module.hysteresis_mode:
                # Add reverse sweep (End -> Start)
                levels_rev = levels_db[::-1]
                full_levels = np.concatenate((levels_db, levels_rev))
                # Create direction tags
                directions = ["fwd"] * len(levels_db) + ["rev"] * len(levels_rev)
            else:
                full_levels = levels_db
                directions = ["fwd"] * len(levels_db)

            total_steps = len(full_levels)

            freq = self.module.test_frequency
            sample_rate = self.module.audio_engine.sample_rate

            # Calibration state
            ref_gain_db = None

            # Pre-calculate wait times
            # 100ms settling time is usually enough for electronics, plus buffer latency
            min_wait = 1.0

            # Pre-allocate buffer for data
            buffer = np.zeros_like(self.module.input_data)

            # Warm-up the audio stream (especially for Mac/Linux startup delays)
            # We wait for the first full buffer to be filled to ensure the stream is active and running.
            self.module.wait_for_buffer(self._stop_event)

            for i, (level_db, direction) in enumerate(zip(full_levels, directions, strict=False)):
                if not self.is_running:
                    break

                # Set Amplitude
                # Convert dBFS to Linear
                amp_linear = 10 ** (level_db / 20)
                self.module.gen_amplitude = amp_linear

                # Averaging Loop
                mag_sum = 0.0
                noise_sum_sq = 0.0

                # Initial wait for settling at this level
                self.wait_interruptible(min_wait)

                # First capture (wait for buffer fill)
                self.module.wait_for_buffer(self._stop_event)

                for avg_idx in range(self.module.averaging_count):
                    if not self.is_running:
                        break

                    if avg_idx > 0:
                        # Wait for fresh buffer
                        self.module.wait_for_buffer(self._stop_event)

                    self.module.get_latest_buffer_into(buffer)

                    # Process
                    if self.module.input_channel == 0:  # Left
                        sig = buffer[:, 0]
                    else:  # Right
                        if buffer.shape[1] > 1:
                            sig = buffer[:, 1]
                        else:
                            sig = buffer[:, 0]

                    # Lock-in measurement (Signal)
                    mag, phase = AudioCalc.calculate_lockin_measurement(
                        sig, freq, sample_rate, phase_ref=0, window_name="blackmanharris"
                    )

                    # Convert to complex for vector averaging (reduces noise floor)
                    # Note: Phase is relative to start of buffer, which is arbitrary unless synced?
                    # AudioCalc.calculate_lockin_measurement usually returns phase relative to specific ref?
                    # The implementation in AudioCalc likely uses a generated ref sine starting at 0 phase for the buffer.
                    # Since our generator runs continuously, the phase of the signal in the buffer drifts relative to the buffer start.
                    # HOWEVER, Linearity is Amplitude-only (Scalar) usually.
                    # Vector averaging requires phase coherence between averages.
                    # Our `get_latest_buffer` is just a ring buffer snapshot. It is NOT triggered.
                    # So the phase will be random for each capture relative to the buffer window.
                    # THUS: We cannot do Vector Averaging (complex sum) unless we have a trigger or phase sync.
                    # We MUST do Magnitude Averaging (Scalar Averaging).
                    # This reduces variance but doesn't lower the noise floor as much as vector averaging.
                    # Given the request is to "reduce deviation" (variance), scalar averaging is correct here.

                    # Wait, if we use LockInAmplifier logic, it tracks phase.
                    # But here in LinearityAnalyzer, we just call static AudioCalc method.
                    # Let's stick to Magnitude Averaging for safety.

                    mag_sum += mag  # Treating as scalar magnitude accumulation

                    # Sideband Noise Measurement
                    noise_freq = freq * 1.15
                    noise_mag, _ = AudioCalc.calculate_lockin_measurement(
                        sig, noise_freq, sample_rate, phase_ref=0, window_name="blackmanharris"
                    )
                    noise_sum_sq += noise_mag**2

                if not self.is_running:
                    break

                # Compute Averages
                avg_mag = mag_sum / self.module.averaging_count
                avg_noise = np.sqrt(noise_sum_sq / self.module.averaging_count)

                meas_db = 20 * np.log10(avg_mag + 1e-15)

                if avg_noise < 1e-15:
                    avg_noise = 1e-15
                snr_db = 20 * np.log10((avg_mag + 1e-15) / avg_noise)

                # Calculate Gain & Linearity Error
                # Gain = Measured - Input
                # Linearity Error = (Measured - Input) - Ref_Gain

                current_gain = meas_db - level_db

                if ref_gain_db is None:
                    # First point is reference (usually the highest level)
                    ref_gain_db = current_gain

                lin_error = current_gain - ref_gain_db

                result = {
                    "input_level": level_db,
                    "measured_level": meas_db,
                    "gain": current_gain,
                    "linearity_error": lin_error,
                    "phase": 0,  # Phase meaningless with scalar averaging
                    "snr": snr_db,
                    "direction": direction,
                }

                self.result_ready.emit(result)
                self.progress.emit(int((i + 1) / total_steps * 100))

            self.finished_sweep.emit()

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.module.stop_analysis()

    def stop(self):
        self.is_running = False
        self._stop_event.set()
        if hasattr(self.module, "_buffer_ready_event"):
            self.module._buffer_ready_event.set()


class LinearityAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.buffer_size = 65536  # Increased buffer size for safety
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_index = 0
        self.is_running = False
        self._buffer_lock = threading.Lock()
        self._buffer_ready_event = threading.Event()
        self._new_frames = 0

        # Generator
        self.test_frequency = 1000.0
        self.gen_amplitude = 0.0
        self.output_channel = 0  # 0=L, 1=R
        self.input_channel = 0

        # Sweep Params
        self.start_level = -5.0
        self.end_level = -120.0
        self.steps = 30
        self.start_level = -5.0
        self.end_level = -120.0
        self.steps = 30
        self.snr_threshold = 10.0
        self.averaging_count = 1
        self.hysteresis_mode = False

        self.callback_id = None
        self.worker = None

        # Audio generation state
        self._phase_rad = 0.0
        self._last_frames = None
        self._last_freq = None
        self._phase_arr = None
        self._phase_inc = None
        self._current_amp = 0.0

    @property
    def name(self) -> str:
        return "Linearity Analyzer"

    @property
    def description(self) -> str:
        return "Measure Linearity Error (Gain Accuracy vs Level)."

    def wait_for_buffer(self, cancel_event=None):
        with self._buffer_lock:
            self._new_frames = 0
            self._buffer_ready_event.clear()

        while not self._buffer_ready_event.is_set():
            if cancel_event and cancel_event.is_set():
                break
            self._buffer_ready_event.wait()

    def get_latest_buffer_into(self, out: np.ndarray) -> None:
        """Writes the current buffer contents ordered chronologically into `out`."""
        with self._buffer_lock:
            idx = self.input_index
            # Part 1: Oldest data (from idx to end)
            part1_len = self.buffer_size - idx
            out[:part1_len] = self.input_data[idx:]

            # Part 2: Newest data (from 0 to idx)
            out[part1_len:] = self.input_data[:idx]

    def get_widget(self):
        return LinearityAnalyzerWidget(self)

    def start_analysis(self):
        if self.is_running:
            logger.warning(f"Already running (callback_id={self.callback_id})")
            return

        # Safety: Ensure we don't leak a callback if state is inconsistent
        if self.callback_id is not None:
            logger.warning(f"Found lingering callback {self.callback_id} during start. Unregistering.")
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

        self.is_running = True

        # Reset generator phase
        self._phase_rad = 0.0
        self._last_frames = None
        self._current_amp = self.gen_amplitude
        self.input_index = 0
        sample_rate = self.audio_engine.sample_rate

        def callback(indata, outdata, frames, time, status):
            # Input
            new_data = None
            if indata.shape[1] >= 2:
                new_data = indata[:, :2]
            elif indata.shape[1] == 1:
                # Mono input -> duplicate
                new_data = np.repeat(indata, 2, axis=1)

            if new_data is not None:
                new_frames = len(new_data)

                with self._buffer_lock:
                    if new_frames >= self.buffer_size:
                        # If incoming data handles the entire buffer or more, just take the last part
                        self.input_data[:] = new_data[-self.buffer_size :]
                        self.input_index = 0
                    else:
                        # Ring buffer write
                        remaining = self.buffer_size - self.input_index
                        if new_frames <= remaining:
                            self.input_data[self.input_index : self.input_index + new_frames] = new_data
                            self.input_index += new_frames
                        else:
                            # Wrap around
                            part1_len = remaining
                            part2_len = new_frames - remaining
                            self.input_data[self.input_index :] = new_data[:part1_len]
                            self.input_data[:part2_len] = new_data[part1_len:]
                            self.input_index = part2_len

                        if self.input_index >= self.buffer_size:
                            self.input_index = 0

                    self._new_frames += new_frames
                    if self._new_frames >= self.buffer_size:
                        self._buffer_ready_event.set()

            # Output
            if self._last_frames != frames or self._last_freq != self.test_frequency:
                self._phase_inc = 2 * np.pi * self.test_frequency / sample_rate
                self._phase_arr = np.arange(frames) * self._phase_inc
                self._last_frames = frames
                self._last_freq = self.test_frequency

            current_phase = self._phase_rad + self._phase_arr
            self._phase_rad = (self._phase_rad + frames * self._phase_inc) % (2 * np.pi)

            # Smoothly transition amplitude to avoid step discontinuities
            target_amp = self.gen_amplitude
            if self._current_amp != target_amp:
                amp_arr = np.linspace(self._current_amp, target_amp, frames)
                self._current_amp = target_amp
            else:
                amp_arr = target_amp

            sig = amp_arr * np.sin(current_phase)

            outdata.fill(0)
            if self.output_channel == 0:
                outdata[:, 0] = sig
            elif self.output_channel == 1:
                if outdata.shape[1] > 1:
                    outdata[:, 1] = sig
            elif self.output_channel == 2:  # Stereo
                outdata[:, 0] = sig
                if outdata.shape[1] > 1:
                    outdata[:, 1] = sig

        cid = self.audio_engine.register_callback(callback)
        self.callback_id = cid
        logger.debug(f"Started analysis. Registered callback {cid}")

    def stop_analysis(self):
        if self.callback_id is not None:
            logger.debug(f"Stopping analysis. Unregistering callback {self.callback_id}")
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        else:
            logger.debug("Stop requested but no callback ID.")
            pass

        self.is_running = False

    def start_sweep(self):
        if self.worker and self.worker.isRunning():
            return

        # Ensure audio is running
        self.start_analysis()

        self.worker = LinearitySweepWorker(self)
        return self.worker

    def stop_sweep(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self.stop_analysis()


class LinearityAnalyzerWidget(QWidget):
    def __init__(self, module: LinearityAnalyzer):
        super().__init__()
        self.module = module

        self.zoom_options = {
            tr("Auto"): None,
            "20.0 dB": 20.0,
            "10.0 dB": 10.0,
            "5.0 dB": 5.0,
            "2.0 dB": 2.0,
            "1.0 dB": 1.0,
            "0.5 dB": 0.5,
            "0.2 dB": 0.2,
            "0.1 dB": 0.1,
            "0.05 dB": 0.05,
            "0.02 dB": 0.02,
            "0.01 dB": 0.01,
        }
        self.current_zoom = 5.0  # Default matches old fixed value

        self.init_ui()

        self.results_x = []
        self.results_error = []
        self.results_gain = []
        self.results_gain = []
        self.results_measured = []  # Store raw measured levels (dBFS)
        self.results_snr = []

    def init_ui(self):
        layout = QHBoxLayout()

        # --- Settings Panel ---
        settings_panel = QWidget()
        settings_panel.setFixedWidth(320)  # Slightly wider for tabs
        settings_layout = QVBoxLayout(settings_panel)

        self.tabs = QTabWidget()
        settings_layout.addWidget(self.tabs)

        # Tab 1: Configuration
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        # config_layout.setContentsMargins(5, 5, 5, 5) # Compact

        # Controls
        group = QGroupBox(tr("Sweep Settings"))
        form = QFormLayout()

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(1000)
        self.freq_spin.setSuffix(" Hz")
        self.freq_spin.valueChanged.connect(lambda v: setattr(self.module, "test_frequency", v))
        form.addRow(tr("Frequency:"), self.freq_spin)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(-140, 0)
        self.start_spin.setValue(-5)
        self.start_spin.setSuffix(" dBFS")
        self.start_spin.valueChanged.connect(lambda v: setattr(self.module, "start_level", v))
        form.addRow(tr("Start Level:"), self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(-140, 0)
        self.end_spin.setValue(-120)
        self.end_spin.setSuffix(" dBFS")
        self.end_spin.valueChanged.connect(lambda v: setattr(self.module, "end_level", v))
        form.addRow(tr("End Level:"), self.end_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(2, 200)
        self.steps_spin.setValue(30)
        self.steps_spin.valueChanged.connect(lambda v: setattr(self.module, "steps", v))
        form.addRow(tr("Steps:"), self.steps_spin)

        self.snr_spin = QDoubleSpinBox()
        self.snr_spin.setRange(0, 100)
        self.snr_spin.setValue(10)
        self.snr_spin.setSuffix(" dB")
        self.snr_spin.valueChanged.connect(lambda v: setattr(self.module, "snr_threshold", v))
        form.addRow(tr("SNR Limit:"), self.snr_spin)

        self.avg_spin = QSpinBox()
        self.avg_spin.setRange(1, 100)
        self.avg_spin.setValue(1)
        self.avg_spin.valueChanged.connect(lambda v: setattr(self.module, "averaging_count", v))
        form.addRow(tr("Averaging:"), self.avg_spin)

        group.setLayout(form)
        config_layout.addWidget(group)

        config_layout.addWidget(group)

        # IO
        io_group = QGroupBox(tr("I/O Routing"))
        io_form = QFormLayout()

        self.out_combo = QComboBox()
        self.out_combo.addItems([tr("Left"), tr("Right"), tr("Stereo")])
        self.out_combo.currentIndexChanged.connect(lambda v: setattr(self.module, "output_channel", v))
        io_form.addRow(tr("Output:"), self.out_combo)

        self.in_combo = QComboBox()
        self.in_combo.addItems([tr("Left"), tr("Right")])
        self.in_combo.currentIndexChanged.connect(lambda v: setattr(self.module, "input_channel", v))
        io_form.addRow(tr("Input:"), self.in_combo)

        # Hysteresis Toggle
        from PyQt6.QtWidgets import QCheckBox

        self.hyst_check = QCheckBox(tr("Enable Hysteresis Sweep"))
        self.hyst_check.toggled.connect(lambda v: setattr(self.module, "hysteresis_mode", v))
        io_form.addRow(self.hyst_check)

        io_group.setLayout(io_form)
        config_layout.addWidget(io_group)

        config_layout.addStretch()
        self.tabs.addTab(config_tab, tr("Settings"))

        # Tab 2: Results & Display
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)

        # Display Settings
        disp_group = QGroupBox(tr("Display"))
        disp_form = QFormLayout()

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dBFS", "dBV"])
        self.unit_combo.currentIndexChanged.connect(self.update_plots)
        disp_form.addRow(tr("Unit:"), self.unit_combo)

        disp_group.setLayout(disp_form)
        results_layout.addWidget(disp_group)

        # Statistics
        stats_group = QGroupBox(tr("Statistics"))
        stats_layout = QFormLayout()

        self.stat_ref_gain = QLabel("-- dB")
        self.stat_max_error = QLabel("-- dB")
        self.stat_linear_range = QLabel("-- dB")
        self.stat_slope = QLabel("--")
        self.stat_hysteresis = QLabel("--")

        stats_layout.addRow(tr("Ref Gain:"), self.stat_ref_gain)
        stats_layout.addRow(tr("Max Deviation:"), self.stat_max_error)
        stats_layout.addRow(tr("Linear Range (<0.5dB):"), self.stat_linear_range)  # Using 0.5dB as standard
        stats_layout.addRow(tr("Slope:"), self.stat_slope)
        stats_layout.addRow(tr("Hysteresis Width:"), self.stat_hysteresis)

        stats_group.setLayout(stats_layout)
        results_layout.addWidget(stats_group)

        # Plot Controls
        plot_ctrl_group = QGroupBox(tr("Plot Controls"))
        plot_ctrl_layout = QFormLayout()

        self.zoom_combo = QComboBox()
        self.zoom_keys = list(self.zoom_options.keys())
        self.zoom_combo.addItems(self.zoom_keys)
        self.zoom_combo.setCurrentText("5.0 dB")
        self.zoom_combo.currentTextChanged.connect(self.on_zoom_changed)
        plot_ctrl_layout.addRow(tr("Y-Axis Zoom:"), self.zoom_combo)

        plot_ctrl_group.setLayout(plot_ctrl_layout)
        results_layout.addWidget(plot_ctrl_group)

        results_layout.addStretch()
        self.tabs.addTab(results_tab, tr("Results"))

        # Run Controls (Persistent)
        self.start_btn = QPushButton(tr("Start Sweep"))
        self.start_btn.setCheckable(True)
        self.start_btn.clicked.connect(self.on_start_stop)
        self.start_btn.setFixedHeight(50)
        settings_layout.addWidget(self.start_btn)

        self.progress = QProgressBar()
        settings_layout.addWidget(self.progress)

        settings_layout.addStretch()  # Bottom stretch for the whole panel
        layout.addWidget(settings_panel)

        # --- Plots ---
        plot_layout = QVBoxLayout()

        # Plot 1: Linearity Error
        self.error_plot = pg.PlotWidget(title=tr("Linearity Error (Deviation)"))
        self.error_plot.setLabel("left", tr("Error"), units="dB")
        self.error_plot.setLabel("bottom", tr("Input Level"), units="dBFS")
        self.error_plot.showGrid(x=True, y=True)
        self.error_plot.setYRange(-5, 5)  # Typical range focus
        self.error_curve = self.error_plot.plot(pen=pg.mkPen("r", width=3), symbol="o")

        # Noise Floor Region
        # Gray band indicating measurement limit
        self.noise_region = pg.LinearRegionItem(
            orientation=pg.LinearRegionItem.Vertical, brush=pg.mkBrush(100, 100, 100, 50), movable=False
        )
        for line in self.noise_region.lines:
            line.setPen(pg.mkPen((150, 150, 150), width=1, style=Qt.PenStyle.DashLine))
        self.noise_region.setRegion([-140, -140])  # Hidden initially
        self.error_plot.addItem(self.noise_region, ignoreBounds=True)

        # Label for noise region
        self.noise_label = pg.TextItem(text=tr("Below Noise Floor"), color=(150, 150, 150), anchor=(0, 1))
        self.error_plot.addItem(self.noise_label)
        self.noise_label.setVisible(False)

        # Tolerance lines (+/- 1dB)
        self.tol_line_plus = pg.InfiniteLine(
            angle=0, pos=1.0, pen=pg.mkPen((0, 200, 0), width=1, style=Qt.PenStyle.DashLine)
        )
        self.tol_line_minus = pg.InfiniteLine(
            angle=0, pos=-1.0, pen=pg.mkPen((0, 200, 0), width=1, style=Qt.PenStyle.DashLine)
        )
        self.error_plot.addItem(self.tol_line_plus)
        self.error_plot.addItem(self.tol_line_minus)

        plot_layout.addWidget(self.error_plot)

        # Plot 2: Absolute Gain
        self.gain_plot = pg.PlotWidget(title=tr("Absolute Gain"))
        self.gain_plot.setLabel("left", tr("Gain"), units="dB")
        self.gain_plot.setLabel("bottom", tr("Input Level"), units="dBFS")
        self.gain_plot.showGrid(x=True, y=True)
        self.gain_curve = self.gain_plot.plot(pen="y", symbol="+")

        plot_layout.addWidget(self.gain_plot)

        layout.addLayout(plot_layout)

        self.setLayout(layout)

    def on_start_stop(self):
        if self.start_btn.isChecked():
            self.results_x = []
            self.results_error = []
            self.results_gain = []
            self.results_gain = []
            self.results_measured = []
            self.results_snr = []
            self.results_direction = []
            self.error_curve.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead
            self.error_curve.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead
            self.gain_curve.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead

            # Reset Stats
            self.stat_ref_gain.setText("-- dB")
            self.stat_max_error.setText("-- dB")
            self.stat_linear_range.setText("-- dB")
            self.stat_slope.setText("--")
            self.stat_hysteresis.setText("--")

            worker = self.module.start_sweep()
            worker.progress.connect(self.progress.setValue)
            worker.result_ready.connect(self.on_result)
            worker.finished_sweep.connect(self.on_finished)
            worker.error.connect(self.on_error)
            worker.start()

            self.start_btn.setText(tr("Stop"))
        else:
            self.module.stop_sweep()
            self.start_btn.setText(tr("Start Sweep"))

    def on_zoom_changed(self, text):
        val = self.zoom_options.get(text)
        self.current_zoom = val
        self.update_plots()

    def on_result(self, res):
        self.results_x.append(res["input_level"])
        self.results_error.append(res["linearity_error"])
        self.results_gain.append(res["gain"])
        self.results_measured.append(res["measured_level"])
        self.results_snr.append(res["snr"])
        self.results_direction.append(res.get("direction", "fwd"))

        self.update_plots()
        self.update_stats()

    def update_plots(self):
        if not self.results_x:
            return

        unit = self.unit_combo.currentText()

        x_data = np.array(self.results_x)
        error_data = np.array(self.results_error)
        gain_data = np.array(self.results_gain)
        measured_data = np.array(self.results_measured)

        if unit == "dBV":
            # Convert X (Input Level dBFS) to dBV
            # Input is generated, so use Output Gain calibration
            # Input dBV = Input dBFS + 20*log10(OutputGain)
            # Note: module.audio_engine.calibration is accessible
            cal = self.module.audio_engine.calibration
            # We need Output Gain to know what voltage we sent
            # Wait, Output Gain is usually "Volts per FS"
            # So dBV = dBFS + 20*log10(v_per_fs)
            try:
                out_gain_db = 20 * np.log10(cal.output_gain)
            except Exception:
                out_gain_db = 0

            x_plot = x_data + out_gain_db

            # For the "Gain/Measured" plot:
            # If dBV, we probably want to see Measured Level in dBV vs Input Level in dBV
            # Measured dBFS to dBV using Input Sensitivity
            try:
                in_sens_db = 20 * np.log10(cal.input_sensitivity)
            except Exception:
                in_sens_db = 0

            y_plot_2 = measured_data + in_sens_db

            # Update Labels
            self.error_plot.setLabel("bottom", tr("Input Level"), units="dBV")
            self.gain_plot.setTitle(tr("Measured Level"))
            self.gain_plot.setLabel("left", tr("Level"), units="dBV")
            self.gain_plot.setLabel("bottom", tr("Input Level"), units="dBV")

        else:  # dBFS
            x_plot = x_data
            y_plot_2 = gain_data  # Show Gain in dB

            # Offset for region calculation is 0
            out_gain_db = 0

            self.error_plot.setLabel("bottom", tr("Input Level"), units="dBFS")
            self.gain_plot.setTitle(tr("Absolute Gain"))
            self.gain_plot.setLabel("left", tr("Gain"), units="dB")
            self.gain_plot.setLabel("bottom", tr("Input Level"), units="dBFS")

        self.error_curve.setData(x_plot, error_data)
        self.gain_curve.setData(x_plot, y_plot_2)

        # Update Noise Region
        if hasattr(self, "results_snr") and self.results_snr:
            snr_data = np.array(self.results_snr)
            threshold = self.module.snr_threshold

            # Find Noise Limit (Highest Input Level where SNR < Threshold)
            # Use original x_data (dBFS) for sorting, then apply offset
            sorted_indices = np.argsort(x_data)
            x_sorted = x_data[sorted_indices]
            snr_sorted = snr_data[sorted_indices]

            limit_dbfs = None
            # Scan from High to Low
            for i in range(len(x_sorted) - 1, -1, -1):
                if snr_sorted[i] < threshold:
                    limit_dbfs = x_sorted[i]
                    break  # Found the highest level that failed (or rather, the boundary)

            # Wait, if sorting Low to High (indexes 0..N), range(len-1, -1, -1) goes High to Low.
            # If [i] is bad, does that mean [i-1] (lower level) is also bad?
            # Yes, usually. So we find the *first* bad point from the top.

            if limit_dbfs is not None:
                region_edge = limit_dbfs + (out_gain_db if unit == "dBV" else 0)
                # Region covers everything to the left
                self.noise_region.setRegion([-200, region_edge])
                self.noise_region.setVisible(True)

                self.noise_label.setPos(region_edge, 4)  # Top of plot
                self.noise_label.setVisible(True)
            else:
                self.noise_region.setVisible(False)
                self.noise_label.setVisible(False)

        # Update Y-Ranges based on Zoom
        if self.current_zoom is not None:
            # Error Plot is always centered at 0
            self.error_plot.setYRange(-self.current_zoom, self.current_zoom)
            self.error_plot.enableAutoRange(y=False)

            # Gain Plot - User requested Auto always
            self.gain_plot.enableAutoRange(y=True)

        else:
            # Auto
            self.error_plot.enableAutoRange(y=True)
            self.gain_plot.enableAutoRange(y=True)

    def update_stats(self):
        if not self.results_gain:
            return

        # 1. Ref Gain (Gain at highest input level)
        # Assuming sorted high-to-low or low-to-high, find max input
        max_input_idx = np.argmax(self.results_x)
        ref_gain = self.results_gain[max_input_idx]
        self.stat_ref_gain.setText(f"{ref_gain:.3f} dB")

        # 2. Max Deviation (Max absolute linearity error)
        errors = np.array(self.results_error)
        max_dev = np.max(np.abs(errors))
        self.stat_max_error.setText(f"{max_dev:.3f} dB")

        # 3. Slope (Linear Regression of Output vs Input)
        # Measured = Input + Gain
        # We want to check how close Measured is to Input + const.
        # Here we just calculate slope of Gain vs Input? No, Gain should be flat (slope 0).
        # OR Measured Level vs Input Level (slope 1).
        # Let's do Gain Slope (should be 0).
        if len(self.results_x) > 1:
            inputs = np.array(self.results_x)
            gains = np.array(self.results_gain)
            # Filter for valid range? E.g. exclude noise floor bottom
            # For now use all points
            slope, _ = np.polyfit(inputs, gains, 1)
            self.stat_slope.setText(f"{slope:.5f} dB/dB")

        # 4. Linear Range (Lowest level where error < 0.5 dB AND SNR > Threshold)
        limit = 0.5

        # Calculate SNR Limit
        snr_threshold = self.module.snr_threshold
        snr_data = np.array(self.results_snr)

        # Sort everything by Input Level
        sorted_indices = np.argsort(self.results_x)[::-1]  # High to Low
        inputs_sorted = np.array(self.results_x)[sorted_indices]
        errors_sorted = errors[sorted_indices]
        snr_sorted = snr_data[sorted_indices]

        # Find first failure (Error > 0.5 OR SNR < Threshold)
        fail_idx = -1
        failures = (np.abs(errors_sorted) > limit) | (snr_sorted < snr_threshold)
        fail_indices = np.where(failures)[0]
        if fail_indices.size > 0:
            fail_idx = fail_indices[0]

        if fail_idx != -1:
            if fail_idx > 0:
                min_good = inputs_sorted[fail_idx - 1]
                self.stat_linear_range.setText(f"> {min_good:.1f} dBFS")
            else:
                self.stat_linear_range.setText(tr("Poor Linearity"))
        else:
            min_good = np.min(self.results_x)
            self.stat_linear_range.setText(f"> {min_good:.1f} dBFS")

        # 5. Hysteresis
        if self.module.hysteresis_mode and len(self.results_direction) > 0:
            max_hyst = calculate_hysteresis(self.results_x, self.results_gain, self.results_direction)
            if max_hyst is not None:
                self.stat_hysteresis.setText(f"{max_hyst:.3f} dB")
            else:
                self.stat_hysteresis.setText("--")
        else:
            self.stat_hysteresis.setText(tr("N/A"))

    def on_finished(self):
        self.start_btn.setChecked(False)
        self.start_btn.setText(tr("Start Sweep"))
        self.module.stop_analysis()
        self.progress.setValue(100)

    def on_error(self, msg):
        self.on_finished()
        QMessageBox.critical(self, tr("Error"), tr("Sweep failed:\n{0}").format(msg))
        logger.error(f"Error: {msg}")
