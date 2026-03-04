import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import pyqtSignal, QObject, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)

# Used for decoupling background thread results to GUI thread safely.
class FinderSignals(QObject):
    result_ready = pyqtSignal(object)
    sweep_started = pyqtSignal(object)
    progress_update = pyqtSignal(int, int, object, object)

class LockInSpectrumFinder(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.lock = threading.Lock()

        # Input buffer (stereo)
        self.buffer_size = 262144
        self.input_data = np.zeros((self.buffer_size, 2))
        self.input_buffer_pos = 0
        self.buffer_filled_samples = 0

        # Analysis parameters
        self.points = 256
        self.start_freq = 20.0
        self.stop_freq = 20000.0
        self.spacing = "Log" # "Lin" or "Log"

        # Audio params
        self.input_channel = 0 # 0: Left, 1: Right

        # State
        self.callback_id = None
        self.signals = FinderSignals()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._calculation_future = None

        # Mode
        self.mode = "Basic" # "Basic" or "Zoom"
        self.zoom_center_freq = 1000.0
        self.zoom_span = 10.0
        self.track_peak = False

        # Analysis Settings
        self.window_type = "none" # "none", "hann", "hamming", "blackmanharris"

        # Display
        self.display_unit = "dBFS" # "dBFS", "dBV", "dB SPL"

    @property
    def name(self) -> str:
        return "Lock-in Spectrum Finder"

    @property
    def description(self) -> str:
        return "High-resolution spectrum finder using parallel lock-in detection (matrix projection)."

    def get_widget(self):
        return LockInSpectrumFinderWidget(self)

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True

        with self.lock:
            self.input_data = np.zeros((self.buffer_size, 2))
            self.input_buffer_pos = 0
            self.buffer_filled_samples = 0

        def callback(indata, outdata, frames, time, status):
            if not self.is_running:
                outdata.fill(0)
                return

            outdata.fill(0) # Not generating any signal currently

            if indata.shape[1] >= 2:
                new_data = indata[:, :2]
            else:
                new_data = np.column_stack((indata[:, 0], indata[:, 0]))

            n = len(new_data)

            with self.lock:
                p = self.input_buffer_pos
                if p + n <= self.buffer_size:
                    self.input_data[p : p + n] = new_data
                    self.input_buffer_pos = (p + n) % self.buffer_size
                else:
                    chunk1 = self.buffer_size - p
                    chunk2 = n - chunk1
                    self.input_data[p:] = new_data[:chunk1]
                    self.input_data[:chunk2] = new_data[chunk1:]
                    self.input_buffer_pos = chunk2

                self.buffer_filled_samples = min(self.buffer_size, self.buffer_filled_samples + n)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            self.is_running = False
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None

    def clear_buffer(self):
        with self.lock:
            self.input_data.fill(0)
            self.input_buffer_pos = 0
            self.buffer_filled_samples = 0

    def get_data_snapshot(self):
        with self.lock:
            if self.buffer_filled_samples < self.buffer_size:
                return None
            data = self.input_data.copy()
            pos = self.input_buffer_pos

        if pos == 0:
            return data
        return np.concatenate((data[pos:], data[:pos]))

    def trigger_calculation(self):
        """Called by GUI timer to check if ready and submit background job."""
        if not self.is_running:
            return

        data = self.get_data_snapshot()
        if data is None:
            return # Not filled yet

        # Clear buffer immediately to start collecting next chunk while calculating
        self.clear_buffer()

        # Don't queue multiple if one is still running
        if self._calculation_future is not None and not self._calculation_future.done():
            # A calculation is already in progress, drop this frame or wait.
            # Dropping is safer to prevent queue explosion.
            return

        sig = data[:, self.input_channel]
        fs = self.audio_engine.sample_rate

        # Capture current params safely
        p_start = self.start_freq
        p_stop = self.stop_freq
        p_points = self.points
        p_spacing = self.spacing
        p_unit = self.display_unit
        p_offset_dbv = self.audio_engine.calibration.get_input_offset_db()
        p_offset_spl = self.audio_engine.calibration.get_spl_offset_db()
        p_mode = self.mode
        p_zoom_center = self.zoom_center_freq
        p_zoom_span = self.zoom_span
        p_window = self.window_type

        self._calculation_future = self.executor.submit(
            self._do_calculation, sig, fs, p_start, p_stop, p_points, p_spacing, 
            p_unit, p_offset_dbv, p_offset_spl, p_mode, p_zoom_center, p_zoom_span, p_window
        )

    def _do_calculation(self, sig, fs, start_f, stop_f, points, spacing,
                        display_unit, offset_dbv, offset_spl,
                        mode="Basic", zoom_center=1000.0, zoom_span=10.0, window_type="none"):
        """
        Background heavy lifting: Matrix projection or Zoom DDC
        """
        import time
        import scipy.signal as signal
        N = len(sig)
        t = np.arange(N, dtype=np.float64) / fs

        if mode == "Zoom":
            s_f = zoom_center - zoom_span
            e_f = zoom_center + zoom_span
            freqs = np.linspace(s_f, e_f, points)
            self.signals.sweep_started.emit(freqs)

            # 1. Baseband mixing (DDC)
            sig_c = sig * np.exp(-1j * 2 * np.pi * zoom_center * t)

            # 2. Decimate to reduce points
            # 巨大な間引き率によるハングを防ぐため、100Hz以上のサンプリングレートを維持
            target_fs = max(zoom_span * 4, 100.0)
            M = max(1, int(fs / target_fs))

            if M > 1:
                sig_dec = signal.resample_poly(sig_c, 1, M)
            else:
                sig_dec = sig_c

            fs_dec = fs / M
            N_dec = len(sig_dec)
            t_dec = np.arange(N_dec) / fs_dec

            freqs_offset = np.linspace(-zoom_span, zoom_span, points)
            mags_db_all = np.zeros(points)

            # --- 窓関数の適用 ---
            if window_type == "none":
                window = np.ones(N_dec, dtype=np.float64)
                sig_dec_win = sig_dec
                window_coherent_gain = 1.0
            else:
                window = signal.get_window(window_type, N_dec)
                sig_dec_win = sig_dec * window
                window_coherent_gain = np.mean(window)
                if window_coherent_gain == 0:
                    window_coherent_gain = 1.0

            chunk_size = 32
            for i in range(0, points, chunk_size):
                if not self.is_running:
                    break
                end_idx = min(i + chunk_size, points)
                f_chunk = freqs_offset[i:end_idx]
                phase = t_dec[:, np.newaxis] * f_chunk
                exp_chunk = np.exp(-2j * np.pi * phase)
                # Direct correlation on decimated baseband with windowing (vectorized)
                vals = (sig_dec_win @ exp_chunk) / (N_dec * window_coherent_gain)
                amp = np.abs(vals) * 2.0
                if display_unit in ["dBV", "dB SPL"]:
                    amp /= np.sqrt(2.0)

                mags_db_chunk = 20.0 * np.log10(amp + 1e-15)
                if display_unit == "dBV":
                    mags_db_chunk += offset_dbv
                elif display_unit == "dB SPL" and offset_spl is not None:
                    mags_db_chunk += offset_spl

                mags_db_all[i:end_idx] = mags_db_chunk

                # Emit result chunk back to GUI thread
                self.signals.progress_update.emit(i, end_idx, freqs[i:end_idx], mags_db_chunk)
                time.sleep(0.005)

            if self.is_running:
                self.signals.result_ready.emit((freqs, mags_db_all))
            return

        # Basic Mode (Matrix Projection)
        if spacing == "Log":
            # Avoid log of 0 or negative
            s_f = max(0.1, start_f)
            freqs = np.logspace(np.log10(s_f), np.log10(stop_f), points)
        elif spacing == "Integer":
            freqs = np.unique(np.round(np.linspace(start_f, stop_f, points)))
            points = len(freqs)
        else:
            freqs = np.linspace(start_f, stop_f, points)

        self.signals.sweep_started.emit(freqs)

        # To prevent CPU overallocation and buffer underruns, we process in chunks.
        # This spreads the load and allows for progressive UI updates (sliding line).
        chunk_size = 32
        mags_db_all = np.zeros(points)

        # --- 初期窓関数の適用 (指定された窓関数) ---
        # このNはsig全体の長さ
        import scipy.signal as signal
        if window_type == "none":
            window_orig = np.ones(N, dtype=np.float64)
        else:
            window_orig = signal.get_window(window_type, N)
        sqrt_win_orig = np.sqrt(np.maximum(window_orig, 0.0))
        sig_win_orig = sig * sqrt_win_orig

        for i in range(0, points, chunk_size):
            if not self.is_running:
                break

            end_idx = min(i + chunk_size, points)
            current_points = end_idx - i
            num_bases = 1 + current_points * 2
            f_chunk = freqs[i:end_idx]

            # --- Multi-rate downsampling ---
            max_f = f_chunk[-1]
            target_fs = max_f * 4.0
            M = max(1, int(fs / target_fs))

            if M > 1:
                sig_dec = signal.resample_poly(sig, 1, M)
                N_chunk = len(sig_dec)
                fs_dec = fs / M
                if window_type == "none":
                    window_dec = np.ones(N_chunk, dtype=np.float64)
                else:
                    window_dec = signal.get_window(window_type, N_chunk)
                sqrt_win = np.sqrt(np.maximum(window_dec, 0.0))
                sig_win = sig_dec * sqrt_win
                t_chunk = np.arange(N_chunk, dtype=np.float64) / fs_dec
            else:
                N_chunk = N
                fs_dec = fs
                sqrt_win = sqrt_win_orig
                sig_win = sig_win_orig
                t_chunk = t

            two_pi_t = 2.0 * np.pi * t_chunk
            phase = two_pi_t[:, np.newaxis] * f_chunk

            # Allocate Windowed Basis Matrix for the local chunk
            # [1, cos(w1), sin(w1), cos(w1), sin(w1), ...]
            B_win = np.empty((N_chunk, num_bases), dtype=np.float64) # 高精度化 (float64)
            B_win[:, 0] = sqrt_win # DC includes the window weight

            # Compute and apply window weight directly in pre-allocated array
            np.cos(phase, out=B_win[:, 1::2])
            B_win[:, 1::2] *= sqrt_win[:, np.newaxis]

            np.sin(phase, out=B_win[:, 2::2])
            B_win[:, 2::2] *= sqrt_win[:, np.newaxis]

            # Free memory immediately
            del phase

            # Since B can be huge, we use Gram directly for speed:
            gram = np.dot(B_win.T, B_win)
            rhs = np.dot(B_win.T, sig_win)

            try:
                # try speedy solve
                coeff = np.linalg.solve(gram, rhs)
            except np.linalg.LinAlgError:
                # fallback
                coeff = np.linalg.lstsq(B_win, sig_win, rcond=None)[0]

            # Extract magnitudes for this chunk
            X = coeff[1:]
            iq = X.reshape(-1, 2)
            amp = np.hypot(iq[:, 0], iq[:, 1])
            if display_unit in ["dBV", "dB SPL"]:
                amp /= np.sqrt(2.0)

            mags_db_chunk = 20.0 * np.log10(amp + 1e-15)
            if display_unit == "dBV":
                mags_db_chunk += offset_dbv
            elif display_unit == "dB SPL" and offset_spl is not None:
                mags_db_chunk += offset_spl

            mags_db_all[i:end_idx] = mags_db_chunk

            # Emit result chunk back to GUI thread
            self.signals.progress_update.emit(i, end_idx, freqs[i:end_idx], mags_db_chunk)

            # Sleep briefly to ensure audio callback is not starved 
            time.sleep(0.005)

        if self.is_running:
            self.signals.result_ready.emit((freqs, mags_db_all))

class LockInSpectrumFinderWidget(QWidget):
    def __init__(self, module: LockInSpectrumFinder):
        super().__init__()
        self.module = module
        self.init_ui()

        self.module.signals.result_ready.connect(self.on_result_ready)
        self.module.signals.sweep_started.connect(self.on_sweep_started)
        self.module.signals.progress_update.connect(self.on_progress_update)

        self.timer = QTimer()
        self.timer.timeout.connect(self.check_calculation)
        self.timer.setInterval(100) # Check every 100ms

    def init_ui(self):
        layout = QHBoxLayout()

        # LEFT: Controls
        left_panel = QVBoxLayout()
        settings_group = QGroupBox(tr("Settings"))
        form = QFormLayout()

        self.btn_toggle = QPushButton(tr("Start Analysis"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle)
        self.btn_toggle.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        form.addRow(self.btn_toggle)

        # Mode Selection
        self.combo_mode = QComboBox()
        self.combo_mode.addItem(tr("Basic"), "Basic")
        self.combo_mode.addItem(tr("Zoom"), "Zoom")
        idx = self.combo_mode.findData(self.module.mode)
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.combo_mode.currentIndexChanged.connect(self.on_mode_changed)
        form.addRow(tr("Mode:"), self.combo_mode)

        # Averages (EMA)
        self.lbl_averages = QLabel(tr("Averages:"))
        self.spin_averages = QSpinBox()
        self.spin_averages.setRange(1, 1000)
        self.spin_averages.setValue(1)
        self.spin_averages.valueChanged.connect(self.on_averages_changed)
        form.addRow(self.lbl_averages, self.spin_averages)

        # Buffer size
        self.combo_buffer = QComboBox()
        self._update_buffer_options()
        form.addRow(tr("Buffer Size:"), self.combo_buffer)

        # Input Channel
        self.combo_input_ch = QComboBox()
        self.combo_input_ch.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)")])
        self.combo_input_ch.setCurrentIndex(self.module.input_channel)
        self.combo_input_ch.currentIndexChanged.connect(self.on_input_ch_changed)
        form.addRow(tr("Input Ch:"), self.combo_input_ch)

        # Grid settings
        self.spin_points = QSpinBox()
        self.spin_points.setRange(16, 1024)
        self.spin_points.setValue(self.module.points)
        self.spin_points.setSingleStep(32)
        self.spin_points.valueChanged.connect(self.on_points_changed)
        form.addRow(tr("Basis Points:"), self.spin_points)

        # Window Function
        self.lbl_window = QLabel(tr("Window:"))
        self.combo_window = QComboBox()
        self.combo_window.addItems(["none", "blackmanharris", "hann", "hamming"])
        self.combo_window.setCurrentText(self.module.window_type)
        self.combo_window.currentTextChanged.connect(self.on_window_changed)
        form.addRow(self.lbl_window, self.combo_window)

        # Display Unit
        self.lbl_unit = QLabel(tr("Display Unit:"))
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["dBFS", "dBV", "dB SPL"])
        self.combo_unit.setCurrentText(self.module.display_unit)
        self.combo_unit.currentTextChanged.connect(self.on_unit_changed)
        form.addRow(self.lbl_unit, self.combo_unit)

        self.lbl_start_f = QLabel(tr("Start Freq:"))
        self.spin_start_f = QDoubleSpinBox()
        self.spin_start_f.setRange(1.0, 96000.0)
        self.spin_start_f.setValue(self.module.start_freq)
        self.spin_start_f.setSuffix(" Hz")
        self.spin_start_f.valueChanged.connect(self.on_start_f_changed)
        form.addRow(self.lbl_start_f, self.spin_start_f)

        self.lbl_stop_f = QLabel(tr("Stop Freq:"))
        self.spin_stop_f = QDoubleSpinBox()
        self.spin_stop_f.setRange(10.0, 96000.0)
        self.spin_stop_f.setValue(self.module.stop_freq)
        self.spin_stop_f.setSuffix(" Hz")
        self.spin_stop_f.valueChanged.connect(self.on_stop_f_changed)
        form.addRow(self.lbl_stop_f, self.spin_stop_f)

        self.lbl_spacing = QLabel(tr("Spacing:"))
        self.combo_spacing = QComboBox()
        self.combo_spacing.addItem(tr("Log"), "Log")
        self.combo_spacing.addItem(tr("Lin"), "Lin")
        self.combo_spacing.addItem(tr("Integer"), "Integer")
        idx = self.combo_spacing.findData(self.module.spacing)
        if idx >= 0:
            self.combo_spacing.setCurrentIndex(idx)
        self.combo_spacing.currentIndexChanged.connect(self.on_spacing_changed)
        form.addRow(self.lbl_spacing, self.combo_spacing)

        # Zoom Mode Fields
        self.lbl_zoom_center = QLabel(tr("Zoom Center:"))
        self.spin_zoom_center = QDoubleSpinBox()
        self.spin_zoom_center.setRange(1.0, 96000.0)
        self.spin_zoom_center.setValue(self.module.zoom_center_freq)
        self.spin_zoom_center.setSuffix(" Hz")
        self.spin_zoom_center.valueChanged.connect(self.on_zoom_center_changed)
        
        self.chk_track_peak = QCheckBox(tr("Track Peak"))
        self.chk_track_peak.setChecked(self.module.track_peak)
        self.chk_track_peak.stateChanged.connect(self.on_track_peak_changed)
        
        hbox_zoom_center = QHBoxLayout()
        hbox_zoom_center.setContentsMargins(0, 0, 0, 0)
        hbox_zoom_center.addWidget(self.spin_zoom_center)
        hbox_zoom_center.addWidget(self.chk_track_peak)
        form.addRow(self.lbl_zoom_center, hbox_zoom_center)

        self.lbl_zoom_span = QLabel(tr("Zoom Span (±):"))
        self.spin_zoom_span = QDoubleSpinBox()
        self.spin_zoom_span.setRange(0.1, 10000.0)
        self.spin_zoom_span.setValue(self.module.zoom_span)
        self.spin_zoom_span.setSuffix(" Hz")
        self.spin_zoom_span.valueChanged.connect(self.on_zoom_span_changed)
        form.addRow(self.lbl_zoom_span, self.spin_zoom_span)

        self._update_ui_visibility()

        settings_group.setLayout(form)
        left_panel.addWidget(settings_group)

        # Status Label
        ov_group = QGroupBox(tr("Status"))
        ov_layout = QVBoxLayout()
        self.lbl_status = QLabel(tr("Ready"))
        self.lbl_status.setStyleSheet("font-size: 14px;")
        ov_layout.addWidget(self.lbl_status)
        ov_group.setLayout(ov_layout)
        left_panel.addWidget(ov_group)

        left_panel.addStretch()
        layout.addLayout(left_panel, 1)

        # RIGHT: Plot
        right_panel = QVBoxLayout()
        self.plot = pg.PlotWidget(title=tr("Lock-in Spectrum"))
        self.plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot.setLabel("left", tr("Amplitude"), units=self.module.display_unit)
        self.plot.showGrid(x=True, y=True)
        self.plot.setYRange(-180, 10)
        self.curve = self.plot.plot(pen="y")

        # Initialize Log mode visual
        self._update_plot_log_mode()

        right_panel.addWidget(self.plot)
        layout.addLayout(right_panel, 3)

        self.setLayout(layout)

    def _update_ui_visibility(self):
        is_zoom = self.module.mode == "Zoom"

        self.lbl_start_f.setVisible(not is_zoom)
        self.spin_start_f.setVisible(not is_zoom)
        self.lbl_stop_f.setVisible(not is_zoom)
        self.spin_stop_f.setVisible(not is_zoom)
        self.lbl_spacing.setVisible(not is_zoom)
        self.combo_spacing.setVisible(not is_zoom)

        self.lbl_zoom_center.setVisible(is_zoom)
        self.spin_zoom_center.setVisible(is_zoom)
        self.chk_track_peak.setVisible(is_zoom)
        self.lbl_zoom_span.setVisible(is_zoom)
        self.spin_zoom_span.setVisible(is_zoom)

    def _update_buffer_options(self):
        """Update buffer size choices based on mode."""
        # Block signals to avoid triggering on_buffer_changed during refill
        self.combo_buffer.blockSignals(True)

        current_val = str(self.module.buffer_size)

        if self.module.mode == "Basic":
            # Up to 512k (approx 500k)
            options = ["65536", "131072", "262144", "524288"]
        else:
            # Up to 8M
            options = ["65536", "131072", "262144", "524288", "1048576", "2097152", "4194304", "8388608"]

        self.combo_buffer.clear()
        self.combo_buffer.addItems(options)

        if current_val in options:
            self.combo_buffer.setCurrentText(current_val)
        else:
            # Auto-cap at max available for this mode
            new_val = options[-1]
            self.combo_buffer.setCurrentText(new_val)
            self.module.buffer_size = int(new_val)

        # Re-connect/unblock signals
        try:
            self.combo_buffer.currentTextChanged.disconnect()
        except TypeError:
            pass
        self.combo_buffer.currentTextChanged.connect(self.on_buffer_changed)
        self.combo_buffer.blockSignals(False)

    def _update_plot_log_mode(self):
        if self.module.mode == "Basic" and self.module.spacing == "Log":
            self.plot.getPlotItem().setLogMode(x=True, y=False)
        else:
            self.plot.getPlotItem().setLogMode(x=False, y=False)

    def reset_averaging(self):
        self.averaged_amps = None
        self.frames_counted = 0

    def on_averages_changed(self, val):
        self.reset_averaging()

    def on_mode_changed(self, idx):
        self.module.mode = self.combo_mode.itemData(idx)
        self._update_plot_log_mode()
        self._update_ui_visibility()
        self._update_buffer_options()
        self.reset_averaging()

    def on_toggle(self, checked):
        if checked:
            self.reset_averaging()
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop Analysis"))
            self.lbl_status.setText(tr("Buffering..."))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start Analysis"))
            self.lbl_status.setText(tr("Stopped"))

    def on_buffer_changed(self, text):
        self.module.buffer_size = int(text)
        self.reset_averaging()
        if self.module.is_running:
            self.module.stop_analysis()
            self.module.start_analysis()

    def on_input_ch_changed(self, idx):
        self.module.input_channel = idx
        self.reset_averaging()

    def on_points_changed(self, val):
        self.module.points = val
        self.reset_averaging()

    def on_start_f_changed(self, val):
        self.module.start_freq = val
        self.reset_averaging()

    def on_stop_f_changed(self, val):
        self.module.stop_freq = val
        self.reset_averaging()

    def on_spacing_changed(self, idx):
        self.module.spacing = self.combo_spacing.itemData(idx)
        self._update_plot_log_mode()
        self.reset_averaging()

    def on_zoom_center_changed(self, val):
        self.module.zoom_center_freq = val
        self.reset_averaging()

    def on_zoom_span_changed(self, val):
        self.module.zoom_span = val
        self.reset_averaging()

    def on_track_peak_changed(self, state):
        self.module.track_peak = bool(state)

    def on_window_changed(self, text):
        self.module.window_type = text
        self.reset_averaging()

    def on_unit_changed(self, text):
        self.module.display_unit = text
        self.plot.setLabel("left", tr("Amplitude"), units=text)
        self.reset_averaging()

    def check_calculation(self):
        if not self.module.is_running:
            return

        with self.module.lock:
            filled = self.module.buffer_filled_samples
            size = self.module.buffer_size

        if filled < size:
            pct = int((filled / size) * 100)
            if self.module._calculation_future is None or self.module._calculation_future.done():
                self.lbl_status.setText(tr("Buffering... {}%").format(pct))
            return

        # Trigger background computation
        self.module.trigger_calculation()

    def on_sweep_started(self, freqs):
        self.current_freqs = freqs.copy()

        if not hasattr(self, 'averaged_amps') or self.averaged_amps is None or len(self.averaged_amps) != len(freqs):
            self.averaged_amps = np.zeros(len(freqs))
            self.frames_counted = 0

            # Reset X-axis plot range on new parameters
            # Handle Log scale formatting internally for UI bounds
            xmin, xmax = freqs[0], freqs[-1]
            if self.module.mode == "Basic" and self.module.spacing == "Log" and xmin > 0:
                xmin, xmax = np.log10(xmin), np.log10(xmax)
            self.plot.setXRange(xmin, xmax, padding=0.0)

        if not hasattr(self, 'current_mags') or len(self.current_mags) != len(freqs):
            self.current_mags = np.full(len(freqs), -180.0)

        self.frames_counted += 1

        if not hasattr(self, 'sweep_line'):
            self.sweep_line = pg.InfiniteLine(angle=90, movable=False, pen='r')
            self.plot.addItem(self.sweep_line)

        self.sweep_line.show()
        val = freqs[0]
        if self.module.mode == "Basic" and self.module.spacing == "Log" and val > 0:
            val = np.log10(val)
        self.sweep_line.setValue(val)
        self.lbl_status.setText(tr("Calculating... 0%"))

    def on_progress_update(self, start_idx, end_idx, f_chunk, m_chunk):
        if not hasattr(self, 'current_freqs') or not hasattr(self, 'current_mags'):
            return

        if not hasattr(self, 'averaged_amps') or self.averaged_amps is None or len(self.averaged_amps) != len(self.current_freqs):
            self.averaged_amps = np.zeros(len(self.current_freqs))
            self.frames_counted = 1

        alpha = 1.0 / min(self.spin_averages.value(), max(1, self.frames_counted))

        a_chunk = 10.0 ** (m_chunk / 20.0)

        if self.frames_counted <= 1:
            self.averaged_amps[start_idx:end_idx] = a_chunk
        else:
            self.averaged_amps[start_idx:end_idx] = (1.0 - alpha) * self.averaged_amps[start_idx:end_idx] + alpha * a_chunk

        avg_db = 20.0 * np.log10(self.averaged_amps[start_idx:end_idx] + 1e-15)
        self.current_mags[start_idx:end_idx] = avg_db
        self.curve.setData(self.current_freqs, self.current_mags)

        if hasattr(self, 'sweep_line'):
            self.sweep_line.show()
            val = f_chunk[-1]
            if self.module.mode == "Basic" and self.module.spacing == "Log" and val > 0:
                val = np.log10(val)
            self.sweep_line.setValue(val)
        pct = int((end_idx / len(self.current_freqs)) * 100)
        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = f" [Avg: {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
        self.lbl_status.setText(tr("Calculating... {}%").format(pct) + avg_text)

    def on_result_ready(self, result):
        freqs, mags_db = result
        self.curve.setData(self.current_freqs, self.current_mags)
        if hasattr(self, 'sweep_line'):
            self.sweep_line.hide()

        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = f" [Avg: {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
        self.lbl_status.setText(tr("Spectrum Updated") + avg_text)

        if self.module.mode == "Zoom" and self.module.track_peak:
            peak_idx = int(np.argmax(self.current_mags))
            new_center = float(self.current_freqs[peak_idx])
            if abs(new_center - self.module.zoom_center_freq) > 1e-6:
                self.spin_zoom_center.setValue(new_center)
