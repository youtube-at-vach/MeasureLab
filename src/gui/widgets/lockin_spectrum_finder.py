import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import pyqtSignal, QObject, QTimer
from PyQt6.QtWidgets import (
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
        p_offset = self.audio_engine.calibration.get_input_offset_db()
        p_mode = self.mode
        p_zoom_center = self.zoom_center_freq
        p_zoom_span = self.zoom_span

        self._calculation_future = self.executor.submit(
            self._do_calculation, sig, fs, p_start, p_stop, p_points, p_spacing, p_offset, p_mode, p_zoom_center, p_zoom_span
        )

    def _do_calculation(self, sig, fs, start_f, stop_f, points, spacing, cal_offset, 
                        mode="Basic", zoom_center=1000.0, zoom_span=10.0):
        """
        Background heavy lifting: Matrix projection or Zoom DDC
        """
        import time
        N = len(sig)
        t = np.arange(N) / fs

        if mode == "Zoom":
            import scipy.signal as signal
            s_f = zoom_center - zoom_span
            e_f = zoom_center + zoom_span
            freqs = np.linspace(s_f, e_f, points)
            self.signals.sweep_started.emit(freqs)

            # 1. Baseband mixing (DDC)
            sig_c = sig * np.exp(-1j * 2 * np.pi * zoom_center * t)

            # 2. Decimate to reduce points
            target_fs = max(zoom_span * 4, 10.0)
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

            chunk_size = 32
            for i in range(0, points, chunk_size):
                if not self.is_running:
                    break
                end_idx = min(i + chunk_size, points)
                current_points = end_idx - i

                mags_db_chunk = np.zeros(current_points)
                for j in range(current_points):
                    f_off = freqs_offset[i + j]
                    # Direct correlation on decimated baseband
                    val = np.mean(sig_dec * np.exp(-1j * 2 * np.pi * f_off * t_dec))
                    amp_rms = np.abs(val) * np.sqrt(2.0)
                    mags_db_chunk[j] = 20 * np.log10(amp_rms + 1e-15) + cal_offset

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
        else:
            freqs = np.linspace(start_f, stop_f, points)

        self.signals.sweep_started.emit(freqs)

        # To prevent CPU overallocation and buffer underruns, we process in chunks.
        # This spreads the load and allows for progressive UI updates (sliding line).
        chunk_size = 32
        mags_db_all = np.zeros(points)

        for i in range(0, points, chunk_size):
            if not self.is_running:
                break

            end_idx = min(i + chunk_size, points)
            current_points = end_idx - i

            # Allocate Basis Matrix for the local chunk
            # [1, cos(w1), sin(w1), cos(w2), sin(w2), ...]
            num_bases = 1 + current_points * 2
            B = np.zeros((N, num_bases), dtype=np.float32)
            B[:, 0] = 1.0 # DC

            for j in range(current_points):
                f = freqs[i + j]
                omega = 2.0 * np.pi * f
                phase = omega * t
                idx = 1 + j * 2
                B[:, idx] = np.cos(phase)
                B[:, idx + 1] = np.sin(phase)

            # Since B can be huge, we use Gram directly for speed:
            gram = np.dot(B.T, B)
            rhs = np.dot(B.T, sig)

            try:
                # try speedy solve
                coeff = np.linalg.solve(gram, rhs)
            except np.linalg.LinAlgError:
                # fallback
                coeff = np.linalg.lstsq(B, sig, rcond=None)[0]

            # Extract magnitudes for this chunk
            mags_db_chunk = np.zeros(current_points)
            X = coeff[1:]
            for j in range(current_points):
                I_comp = X[j * 2]
                Q_comp = X[j * 2 + 1]
                amp = np.sqrt(I_comp**2 + Q_comp**2)
                amp_rms = amp / np.sqrt(2.0)
                mags_db_chunk[j] = 20 * np.log10(amp_rms + 1e-15) + cal_offset

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
        form.addRow(self.lbl_zoom_center, self.spin_zoom_center)

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
        self.plot.setLabel("left", tr("Amplitude"), units="dBFS")
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

    def on_mode_changed(self, idx):
        self.module.mode = self.combo_mode.itemData(idx)
        self._update_plot_log_mode()
        self._update_ui_visibility()
        self._update_buffer_options()

    def on_toggle(self, checked):
        if checked:
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
        if self.module.is_running:
            self.module.stop_analysis()
            self.module.start_analysis()

    def on_input_ch_changed(self, idx):
        self.module.input_channel = idx

    def on_points_changed(self, val):
        self.module.points = val

    def on_start_f_changed(self, val):
        self.module.start_freq = val

    def on_stop_f_changed(self, val):
        self.module.stop_freq = val

    def on_spacing_changed(self, idx):
        self.module.spacing = self.combo_spacing.itemData(idx)
        self._update_plot_log_mode()

    def on_zoom_center_changed(self, val):
        self.module.zoom_center_freq = val

    def on_zoom_span_changed(self, val):
        self.module.zoom_span = val

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
        if not hasattr(self, 'current_mags') or len(self.current_mags) != len(freqs):
            self.current_mags = np.full(len(freqs), -180.0)

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
        self.current_mags[start_idx:end_idx] = m_chunk
        self.curve.setData(self.current_freqs, self.current_mags)
        if hasattr(self, 'sweep_line'):
            self.sweep_line.show()
            val = f_chunk[-1]
            if self.module.mode == "Basic" and self.module.spacing == "Log" and val > 0:
                val = np.log10(val)
            self.sweep_line.setValue(val)
        pct = int((end_idx / len(self.current_freqs)) * 100)
        self.lbl_status.setText(tr("Calculating... {}%").format(pct))

    def on_result_ready(self, result):
        freqs, mags_db = result
        self.current_freqs = freqs
        self.current_mags = mags_db
        self.curve.setData(freqs, mags_db)
        if hasattr(self, 'sweep_line'):
            self.sweep_line.hide()
        self.lbl_status.setText(tr("Spectrum Updated"))

