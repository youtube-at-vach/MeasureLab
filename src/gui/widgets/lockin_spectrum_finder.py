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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)

DEFAULT_SCAN_LIST = {
    997.0: "Standard Test Tone (997Hz)",
    1000.0: "Standard Test Tone (1kHz) / USB Frame (1ms)",
    8000.0: "Audio Sample Rate (8kHz) / USB Audio Packet (125µs)",
    11025.0: "Audio Sample Rate (11.025kHz)",
    15625.0: "CRT Horizontal Scan (PAL/SECAM 15.625kHz)",
    15734.0: "CRT Horizontal Scan (NTSC 15.734kHz)",
    16000.0: "Audio Sample Rate (16kHz)",
    19000.0: "FM Pilot Tone (19kHz)",
    20000.0: "Upper Hearing Limit / SMPS Noise (20kHz)",
    22050.0: "Audio Sample Rate (22.05kHz)",
    24000.0: "Audio Sample Rate Base (24kHz)",
    25000.0: "SMPS Noise (25kHz)",
    30000.0: "SMPS Noise (30kHz)",
    31250.0: "CRT Monitor Scan (31.25kHz) / MIDI Baud Rate",
    31468.0: "CRT Monitor Scan / VGA (31.468kHz)",
    31500.0: "LCD / CRT Monitor Scan (31.5kHz)",
    32000.0: "Audio Sample Rate (32kHz)",
    32768.0: "RTC Crystal Oscillator (32.768kHz)",
    37900.0: "CRT Monitor Scan (37.9kHz)",
    38000.0: "FM Stereo Subcarrier (38kHz)",
    40000.0: "Ultrasonic Transducer / SMPS Noise (40kHz)",
    44100.0: "CD Audio (44.1kHz)",
    46875.0: "CRT Monitor Scan (46.875kHz)",
    47202.0: "CRT Monitor Scan (47.202kHz)",
    48000.0: "DAT/Video Audio (48kHz)",
    48400.0: "CRT Monitor Scan (48.4kHz)",
    50000.0: "SMPS Noise (50kHz)",
    57000.0: "RDS / RBDS (57kHz)",
    60000.0: "SMPS Noise (60kHz)",
    62936.0: "CRT Monitor Scan (62.936kHz)",
    80000.0: "SMPS Noise (80kHz)",
    88200.0: "Hi-Res Audio (88.2kHz)",
    96000.0: "Hi-Res Audio (96kHz)",
    100000.0: "SMPS Noise (100kHz)"
}

def _get_mains_note(base: int, order: int) -> str:
    freq = base * order
    if order == 1:
        return f"Mains Power ({base}Hz)"
    elif order == 2:
        return f"Rectified Mains ({freq}Hz)"
    else:
        suffix = "th"
        if order == 3:
            suffix = "rd"
        return f"Mains {order}{suffix} Harmonic ({freq}Hz)"

# Generate mains harmonics up to 16th order
for _order in range(1, 17):
    for _base in (50, 60):
        _f = float(_base * _order)
        _note = _get_mains_note(_base, _order)
        if _f in DEFAULT_SCAN_LIST:
            DEFAULT_SCAN_LIST[_f] += f" / {_note}"
        else:
            DEFAULT_SCAN_LIST[_f] = _note


# Used for decoupling background thread results to GUI thread safely.
# Used for decoupling background thread results to GUI thread safely.
class FinderSignals(QObject):
    result_ready = pyqtSignal(object)
    sweep_started = pyqtSignal(object)
    progress_update = pyqtSignal(int, int, object, object, object)

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
        self.mode = "Scan" # "Scan" or "Zoom"
        self.zoom_center_freq = 1000.0
        self.zoom_span = 10.0
        self.track_peak = False

        # Scan Mode Specifics
        self.include_scan_targets = True
        self.octave_ref_freq = 1000.0

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
        p_include_targets = self.include_scan_targets
        p_octave_ref = self.octave_ref_freq

        self._calculation_future = self.executor.submit(
            self._do_calculation, sig, fs, p_start, p_stop, p_points, p_spacing, 
            p_unit, p_offset_dbv, p_offset_spl, p_mode, p_zoom_center, p_zoom_span, p_window,
            p_include_targets, p_octave_ref
        )

    def _do_calculation(self, sig, fs, start_f, stop_f, points, spacing,
                        display_unit, offset_dbv, offset_spl,
                        mode="Scan", zoom_center=1000.0, zoom_span=10.0, window_type="none",
                        include_targets=True, octave_ref=1000.0):
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
            self.signals.sweep_started.emit((freqs, []))

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

                # Compute Phase
                phases = np.angle(vals)

                # Emit result chunk back to GUI thread
                self.signals.progress_update.emit(i, end_idx, freqs_offset[i:end_idx], mags_db_chunk, phases)
                time.sleep(0.005)

            if self.is_running:
                # phases unmerged across chunks back to main for zoom (optional completeness)
                self.signals.result_ready.emit((freqs, mags_db_all))
            return

        # Scan Mode (Matrix Projection)
        if spacing == "Log":
            # Avoid log of 0 or negative
            s_f = max(0.1, start_f)
            freqs = np.logspace(np.log10(s_f), np.log10(stop_f), points)
        elif spacing == "Integer":
            freqs = np.unique(np.round(np.linspace(start_f, stop_f, points)))
            freqs = freqs[freqs >= 1.0] # Prevent 0 Hz
        elif spacing == "Int x Sync":
            df = fs / N
            freqs = np.unique(np.round(np.linspace(start_f, stop_f, points) / df) * df)
            freqs = freqs[freqs >= df] # Prevent 0 Hz and extremely low frequencies
            if len(freqs) == 0:
                freqs = np.array([df])
        elif spacing.endswith("Octave"):
            try:
                frac = spacing.split(" ")[0].split("/")
                b = float(frac[1]) / float(frac[0])
            except:
                b = 3.0

            n_start = int(np.floor(b * np.log2(start_f / octave_ref)))
            n_stop = int(np.ceil(b * np.log2(stop_f / octave_ref)))
            n_vals = np.arange(n_start, n_stop + 1)
            freqs = octave_ref * (2.0 ** (n_vals / b))
            # Clip bounds exactly
            freqs = freqs[(freqs >= start_f) & (freqs <= stop_f)]
            if len(freqs) == 0:
                freqs = np.array([start_f, stop_f])
        else: # "Lin"
            freqs = np.linspace(start_f, stop_f, points)

        marker_freqs = []
        if include_targets:
            marker_freqs = [f for f in DEFAULT_SCAN_LIST.keys() if start_f < f < stop_f]
            if marker_freqs:
                # np.unique stably sorts and prevents duplicates
                freqs = np.unique(np.concatenate([freqs, marker_freqs]))

        points = len(freqs)

        self.signals.sweep_started.emit((freqs, marker_freqs))

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

            # iq[:,0] is cos component, iq[:,1] is sin component
            # Standard phase from complex is angle(cos - j*sin)
            phases = np.arctan2(-iq[:, 1], iq[:, 0])

            # Emit result chunk back to GUI thread
            self.signals.progress_update.emit(i, end_idx, freqs[i:end_idx], mags_db_chunk, phases)

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
        self.combo_mode.addItem(tr("Scan"), "Scan")
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
        self.spin_start_f.setRange(1.0, 192000.0)
        self.spin_start_f.setValue(self.module.start_freq)
        self.spin_start_f.setSuffix(" Hz")
        self.spin_start_f.valueChanged.connect(self.on_start_f_changed)
        form.addRow(self.lbl_start_f, self.spin_start_f)

        self.lbl_stop_f = QLabel(tr("Stop Freq:"))
        self.spin_stop_f = QDoubleSpinBox()
        self.spin_stop_f.setRange(10.0, 192000.0)
        self.spin_stop_f.setValue(self.module.stop_freq)
        self.spin_stop_f.setSuffix(" Hz")
        self.spin_stop_f.valueChanged.connect(self.on_stop_f_changed)
        form.addRow(self.lbl_stop_f, self.spin_stop_f)

        self.lbl_spacing = QLabel(tr("Spacing:"))
        self.combo_spacing = QComboBox()
        self.combo_spacing.addItem(tr("Log"), "Log")
        self.combo_spacing.addItem(tr("Lin"), "Lin")
        self.combo_spacing.addItem(tr("Integer"), "Integer")
        self.combo_spacing.addItem(tr("Int x Sync"), "Int x Sync")
        self.combo_spacing.addItem(tr("1/3 Octave"), "1/3 Octave")
        self.combo_spacing.addItem(tr("1/6 Octave"), "1/6 Octave")
        self.combo_spacing.addItem(tr("1/12 Octave"), "1/12 Octave")
        self.combo_spacing.addItem(tr("1/24 Octave"), "1/24 Octave")
        self.combo_spacing.addItem(tr("1/48 Octave"), "1/48 Octave")
        self.combo_spacing.addItem(tr("1/96 Octave"), "1/96 Octave")
        idx = self.combo_spacing.findData(self.module.spacing)
        if idx >= 0:
            self.combo_spacing.setCurrentIndex(idx)
        self.combo_spacing.currentIndexChanged.connect(self.on_spacing_changed)
        form.addRow(self.lbl_spacing, self.combo_spacing)

        # Add Include Scan Targets Option
        self.chk_include_targets = QCheckBox(tr("Include Scan Targets"))
        self.chk_include_targets.setChecked(self.module.include_scan_targets)
        self.chk_include_targets.stateChanged.connect(self.on_include_targets_changed)
        form.addRow(tr("Scan Targets:"), self.chk_include_targets)

        self.lbl_octave_ref = QLabel(tr("Octave Ref Freq:"))
        self.spin_octave_ref = QDoubleSpinBox()
        self.spin_octave_ref.setRange(1.0, 192000.0)
        self.spin_octave_ref.setValue(self.module.octave_ref_freq)
        self.spin_octave_ref.setSuffix(" Hz")
        self.spin_octave_ref.valueChanged.connect(self.on_octave_ref_changed)
        form.addRow(self.lbl_octave_ref, self.spin_octave_ref)

        # Zoom Mode Fields
        self.lbl_zoom_center = QLabel(tr("Zoom Center:"))
        self.spin_zoom_center = QDoubleSpinBox()
        self.spin_zoom_center.setRange(1.0, 192000.0)
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

        self.tabs = QTabWidget()
        self.tabs.addTab(settings_group, tr("Settings"))

        # Targets Tab
        target_tab = QWidget()
        target_layout = QVBoxLayout(target_tab)
        target_layout.setContentsMargins(0, 0, 0, 0)

        self.table_targets = QTableWidget(len(DEFAULT_SCAN_LIST), 2)
        self.table_targets.setHorizontalHeaderLabels([tr("Frequency (Hz)"), tr("Cause / Note")])
        self.table_targets.horizontalHeader().setStretchLastSection(True)
        self.table_targets.verticalHeader().setVisible(False)
        self.table_targets.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_targets.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_targets.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        for i, (freq, note) in enumerate(sorted(DEFAULT_SCAN_LIST.items())):
            self.table_targets.setItem(i, 0, QTableWidgetItem(f"{freq:.1f}"))
            self.table_targets.setItem(i, 1, QTableWidgetItem(tr(note)))

        target_layout.addWidget(self.table_targets)
        self.table_targets.cellDoubleClicked.connect(self.on_target_double_clicked)
        self.tabs.addTab(target_tab, tr("Scan Targets"))

        left_panel.addWidget(self.tabs)

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

        self.scatter = pg.ScatterPlotItem(
            size=10, 
            pen=pg.mkPen(None), 
            brush=pg.mkBrush(255, 0, 0, 200), 
            hoverable=True, 
            hoverSize=15,
            tip=self._get_marker_tooltip
        )
        self.plot.addItem(self.scatter)
        self.scatter.sigClicked.connect(self.on_scatter_clicked)

        # Initialize Log mode visual
        self._update_plot_log_mode()

        right_panel.addWidget(self.plot)
        layout.addLayout(right_panel, 3)

        self.setLayout(layout)

    def _get_marker_tooltip(self, x, y, data):
        if not data:
            return ""

        freq = data.get("freq", 0.0)
        mag = data.get("mag", -180.0)
        phase = data.get("phase_deg", 0.0)
        note = data.get("note", "")
        unit = data.get("unit", "")

        text = (
            f"<b>{tr(note)}</b><br>"
            f"{tr('Frequency:')} {freq:.1f} Hz<br>"
            f"{tr('Magnitude:')} {mag:.2f} {unit}<br>"
            f"{tr('Phase:')} {phase:.1f}°"
        )
        return text

    def _update_ui_visibility(self):
        is_zoom = self.module.mode == "Zoom"

        self.lbl_start_f.setVisible(not is_zoom)
        self.spin_start_f.setVisible(not is_zoom)
        self.lbl_stop_f.setVisible(not is_zoom)
        self.spin_stop_f.setVisible(not is_zoom)
        self.lbl_spacing.setVisible(not is_zoom)
        self.combo_spacing.setVisible(not is_zoom)
        self.chk_include_targets.setVisible(not is_zoom)
        self.lbl_octave_ref.setVisible(not is_zoom)
        self.spin_octave_ref.setVisible(not is_zoom)

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

        if self.module.mode == "Scan":
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
        if self.module.mode == "Scan" and self.module.spacing == "Log":
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

    def on_sweep_started(self, payload):
        freqs, marker_freqs = payload
        self.current_freqs = freqs.copy()
        self.current_marker_freqs = marker_freqs

        if not hasattr(self, 'averaged_amps') or self.averaged_amps is None or len(self.averaged_amps) != len(freqs):
            self.averaged_amps = np.zeros(len(freqs))
            self.frames_counted = 0

            # Reset X-axis plot range on new parameters
            # Handle Log scale formatting internally for UI bounds
            xmin, xmax = freqs[0], freqs[-1]
            if self.module.mode == "Scan" and self.module.spacing == "Log" and xmin > 0:
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
        if self.module.mode == "Scan" and self.module.spacing == "Log" and val > 0:
            val = np.log10(val)
        self.sweep_line.setValue(val)
        self.scatter.setData([]) # clear markers
        self.lbl_status.setText(tr("Calculating... 0%"))

    def _update_scatter_plot(self):
        if not hasattr(self, 'current_marker_freqs') or not self.current_marker_freqs:
            self.scatter.setData([])
            return

        pts = []
        for mf in self.current_marker_freqs:
            idx = np.searchsorted(self.current_freqs, mf)
            def check_and_add(i, mf=mf):
                if 0 <= i < len(self.current_freqs) and np.isclose(self.current_freqs[i], mf, atol=1e-3):
                    y = self.current_mags[i]
                    x = mf
                    phase = float(self.current_phases[i]) if hasattr(self, 'current_phases') else 0.0
                    note = DEFAULT_SCAN_LIST.get(mf, "Unknown")
                    unit = self.module.display_unit

                    # Store rich data in the item
                    data_obj = {
                        "freq": mf,
                        "mag": y,
                        "phase_deg": np.degrees(phase),
                        "note": note,
                        "unit": unit
                    }

                    if self.module.mode == "Scan" and self.module.spacing == "Log" and x > 0:
                        x = np.log10(x)
                    if y > -170:
                        pts.append({'pos': (x, y), 'data': data_obj})
                    return True
                return False

            if not check_and_add(idx):
                check_and_add(idx-1)

        self.scatter.setData(pts)

    def on_progress_update(self, start_idx, end_idx, f_chunk, m_chunk, p_chunk):
        if not hasattr(self, 'current_freqs') or not hasattr(self, 'current_mags'):
            return

        if not hasattr(self, 'current_phases') or len(self.current_phases) != len(self.current_freqs):
            self.current_phases = np.zeros(len(self.current_freqs))

        if not hasattr(self, 'averaged_amps') or self.averaged_amps is None or len(self.averaged_amps) != len(self.current_freqs):
            self.averaged_amps = np.zeros(len(self.current_freqs))
            self.frames_counted = 1

        self.current_phases[start_idx:end_idx] = p_chunk

        alpha = 1.0 / min(self.spin_averages.value(), max(1, self.frames_counted))

        a_chunk = 10.0 ** (m_chunk / 20.0)

        if self.frames_counted <= 1:
            self.averaged_amps[start_idx:end_idx] = a_chunk
        else:
            self.averaged_amps[start_idx:end_idx] = (1.0 - alpha) * self.averaged_amps[start_idx:end_idx] + alpha * a_chunk

        avg_db = 20.0 * np.log10(self.averaged_amps[start_idx:end_idx] + 1e-15)
        self.current_mags[start_idx:end_idx] = avg_db
        self.curve.setData(self.current_freqs, self.current_mags)

        self._update_scatter_plot()

        if hasattr(self, 'sweep_line'):
            self.sweep_line.show()
            val = f_chunk[-1]
            if self.module.mode == "Scan" and self.module.spacing == "Log" and val > 0:
                val = np.log10(val)
            self.sweep_line.setValue(val)
        pct = int((end_idx / len(self.current_freqs)) * 100)
        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = f" [{tr('Avg:')} {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
        self.lbl_status.setText(tr("Calculating... {}%").format(pct) + avg_text)

    def on_result_ready(self, result):
        freqs, mags_db = result
        self.curve.setData(self.current_freqs, self.current_mags)
        self._update_scatter_plot()
        if hasattr(self, 'sweep_line'):
            self.sweep_line.hide()

        avg_text = ""
        if self.spin_averages.value() > 1:
            avg_text = f" [{tr('Avg:')} {min(self.spin_averages.value(), self.frames_counted)}/{self.spin_averages.value()}]"
        self.lbl_status.setText(tr("Spectrum Updated") + avg_text)

        if self.module.mode == "Zoom" and self.module.track_peak:
            peak_idx = int(np.argmax(self.current_mags))
            new_center = float(self.current_freqs[peak_idx])
            if abs(new_center - self.module.zoom_center_freq) > 1e-6:
                self.spin_zoom_center.setValue(new_center)

    def on_include_targets_changed(self, state):
        self.module.include_scan_targets = bool(state)
        self.reset_averaging()

    def on_octave_ref_changed(self, val):
        self.module.octave_ref_freq = val
        self.reset_averaging()

    def on_target_double_clicked(self, row, column):
        item = self.table_targets.item(row, 0)
        if item:
            freq = float(item.text())
            self._transition_to_zoom(freq)

    def on_scatter_clicked(self, plot, points):
        if not points:
            return
        data = points[0].data()
        freq = float(data["freq"])
        self._transition_to_zoom(freq)

    def _transition_to_zoom(self, freq):
        idx = self.combo_mode.findData("Zoom")
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self.spin_zoom_center.setValue(freq)
