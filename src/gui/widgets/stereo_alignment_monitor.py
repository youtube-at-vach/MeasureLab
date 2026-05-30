import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import get_window

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.compactable_interface import CompactableWidgetInterface


class StereoAlignmentMonitor(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self._lock = threading.Lock()

        # DSP parameters
        self.fft_size = 4096
        self.smoothing_factor = 0.8  # Exponential moving average for spectra
        self.noise_floor_db = -80.0

        # State buffers
        self.audio_buffer = np.zeros((self.fft_size, 2))
        self.window = get_window("hann", self.fft_size)
        self.freqs = np.zeros(self.fft_size // 2)

        # Smoothed spectra
        self.s_ll = np.zeros(self.fft_size // 2)
        self.s_rr = np.zeros(self.fft_size // 2)
        self.s_lr = np.zeros(self.fft_size // 2, dtype=complex)

        # Calculated Metrics
        self.balance_db = 0.0
        self.freq_match = 0.0
        self.corr_raw = 0.0
        self.center_focus = 0.0
        self.ms_ratio_db = 0.0
        self.phase_issue = 0.0
        self.phase_issue_deg = 0.0

        self.callback_id = None

        # We'll use a local lock or double buffering to avoid thread contentions,
        # but since arrays are small, direct overwrite might be ok.
        # A dirty flag helps.
        self.data_ready = False

        # Volume Gang Error Logger variables
        self.gang_error_data = {}  # {rounded_avg_db: diff_db}
        self.is_logging = False
        self.log_threshold_db = -60.0
        self.current_l_db = -120.0
        self.current_r_db = -120.0
        self.current_diff_db = 0.0

    @property
    def name(self) -> str:
        return "Stereo Alignment Monitor"

    @property
    def description(self) -> str:
        return "Analyzes stereo balance, center focus, and phase correlation across frequencies."

    def get_widget(self):
        return StereoAlignmentMonitorWidget(self)

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True

        self.audio_buffer = np.zeros((self.fft_size, 2))
        self.s_ll = np.zeros(self.fft_size // 2)
        self.s_rr = np.zeros(self.fft_size // 2)
        self.s_lr = np.zeros(self.fft_size // 2, dtype=complex)

        sr = self.audio_engine.sample_rate
        self.freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / sr)[:-1]

        self.callback_id = self.audio_engine.register_callback(self._callback)

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def _callback(self, indata, outdata, frames, time, status):
        # Pass audio through
        outdata.fill(0)

        if indata.shape[1] < 2:
            return  # Mono input, alignment monitor is meaningless

        new_data = indata[:, :2]

        # Shift buffer and insert new data
        if frames >= self.fft_size:
            self.audio_buffer[:] = new_data[-self.fft_size :]
        else:
            self.audio_buffer = np.roll(self.audio_buffer, -frames, axis=0)
            self.audio_buffer[-frames:] = new_data

        # Volume Gang Error Logger: Compute RMS levels (dBFS)
        rms_l = np.sqrt(np.mean(new_data[:, 0] ** 2))
        rms_r = np.sqrt(np.mean(new_data[:, 1] ** 2))

        epsilon = 1e-12
        l_db = 20 * np.log10(rms_l + epsilon)
        r_db = 20 * np.log10(rms_r + epsilon)
        diff_db = l_db - r_db

        new_gang_entry = None
        if self.is_logging:
            avg_level = (l_db + r_db) / 2.0
            if avg_level >= self.log_threshold_db:
                # Binning to round to nearest 0.1 dB to prevent redundant points
                bin_key = round(avg_level, 1)
                new_gang_entry = (bin_key, diff_db)

        # FFT Calculation (Heavy but runs thread-safely outside lock)
        left_windowed = self.audio_buffer[:, 0] * self.window
        right_windowed = self.audio_buffer[:, 1] * self.window

        # RFFT (drop DC and Nyquist for convenience, keep len fft_size//2)
        X_L = np.fft.rfft(left_windowed)[:-1]
        X_R = np.fft.rfft(right_windowed)[:-1]

        # Power spectra
        P_L = np.abs(X_L) ** 2
        P_R = np.abs(X_R) ** 2
        P_LR = X_L * np.conj(X_R)

        # Update all shared state variables under lock to ensure consistency with GUI thread
        with self._lock:
            self.current_l_db = l_db
            self.current_r_db = r_db
            self.current_diff_db = diff_db

            if new_gang_entry is not None:
                b_k, d_v = new_gang_entry
                self.gang_error_data[b_k] = d_v

            # Exponential smoothing
            alpha = self.smoothing_factor
            self.s_ll = alpha * self.s_ll + (1 - alpha) * P_L
            self.s_rr = alpha * self.s_rr + (1 - alpha) * P_R
            self.s_lr = alpha * self.s_lr + (1 - alpha) * P_LR

            # --- Compute Metrics ---
            # Sums for total energy
            e_l = np.sum(self.s_ll)
            e_r = np.sum(self.s_rr)
            total_e = e_l + e_r

            if total_e > epsilon:
                # 1. L/R Balance
                ratio = e_l / (e_r + epsilon)
                self.balance_db = 10.0 * np.log10(ratio)

                # 2. Center Focus
                e_m = (total_e + 2 * np.sum(np.real(self.s_lr))) / 4.0
                e_s = (total_e - 2 * np.sum(np.real(self.s_lr))) / 4.0
                self.center_focus = (e_m / (e_m + e_s + epsilon)) * 100.0
                self.ms_ratio_db = 10.0 * np.log10((e_m + epsilon) / (e_s + epsilon))

                # 3. Phase Issues
                denom = np.sqrt(self.s_ll * self.s_rr) + epsilon
                c_f = np.real(self.s_lr) / denom
                c_f = np.clip(c_f, -1.0, 1.0)

                # Find negatively correlated bins
                neg_mask = c_f < 0
                if np.any(neg_mask):
                    issue_energy = np.sum((self.s_ll[neg_mask] + self.s_rr[neg_mask]) * np.abs(c_f[neg_mask]))
                    self.phase_issue = (issue_energy / total_e) * 100.0
                else:
                    self.phase_issue = 0.0

                # Overall phase angle in degrees
                overall_cross_real = np.sum(np.real(self.s_lr))
                overall_corr = overall_cross_real / (np.sqrt(e_l * e_r) + epsilon)
                overall_corr = np.clip(overall_corr, -1.0, 1.0)
                self.phase_issue_deg = np.arccos(overall_corr) * (180.0 / np.pi)

                # 4. Frequency Match
                peak_power = np.max(self.s_ll + self.s_rr)
                noise_thresh = peak_power * (10 ** (self.noise_floor_db / 10.0))

                sig_mask = (self.s_ll + self.s_rr) > noise_thresh
                if np.sum(sig_mask) > 10:  # Need minimum number of bins
                    log_l = 10 * np.log10(self.s_ll[sig_mask] + epsilon)
                    log_r = 10 * np.log10(self.s_rr[sig_mask] + epsilon)

                    # Pearson corr
                    mean_l = np.mean(log_l)
                    mean_r = np.mean(log_r)
                    var_l = np.sum((log_l - mean_l) ** 2)
                    var_r = np.sum((log_r - mean_r) ** 2)

                    if var_l > epsilon and var_r > epsilon:
                        cov = np.sum((log_l - mean_l) * (log_r - mean_r))
                        corr = cov / np.sqrt(var_l * var_r)
                        self.freq_match = max(0.0, corr) * 100.0
                        self.corr_raw = max(0.0, corr)
                    else:
                        self.freq_match = 100.0  # Flat lines match
                        self.corr_raw = 1.0
                else:
                    self.freq_match = 0.0
                    self.corr_raw = 0.0

            else:
                self.balance_db = 0.0
                self.center_focus = 50.0  # Silence is neither mono nor out-of-phase
                self.ms_ratio_db = 0.0
                self.phase_issue = 0.0
                self.phase_issue_deg = 0.0
                self.freq_match = 0.0
                self.corr_raw = 0.0

            self.data_ready = True


class StereoAlignmentMonitorWidget(QWidget, CompactableWidgetInterface):
    def __init__(self, module: StereoAlignmentMonitor):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_display)
        self.timer.setInterval(33)  # ~30 FPS

        self.init_ui()

    def init_ui(self):
        self.tabs = QTabWidget(self)

        # 1. Realtime Monitor Tab
        self.tab_realtime = QWidget()
        self.init_realtime_tab()
        self.tabs.addTab(self.tab_realtime, tr("Realtime Monitor"))

        # 2. Volume Gang Error Logger Tab
        self.tab_gang_error = QWidget()
        self.init_gang_error_tab()
        self.tabs.addTab(self.tab_gang_error, tr("Volume Gang Error Logger"))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.tabs)

    def init_realtime_tab(self):
        main_layout = QHBoxLayout(self.tab_realtime)

        # === Left: Visualizations ===
        viz_layout = QVBoxLayout()

        # 1. FFT Difference Plot
        self.fft_plot = pg.PlotWidget(title=tr("L/R Difference FFT (Tone Color Shift)"))
        self.fft_plot.setLogMode(x=True, y=False)
        self.fft_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.fft_plot.setLabel("left", tr("Magnitude"), units="dBFS")
        self.fft_plot.showGrid(x=True, y=True, alpha=0.3)
        self.fft_plot.setXRange(np.log10(20), np.log10(20000))
        self.fft_plot.setYRange(-100, 0)

        self.curve_l = self.fft_plot.plot(pen=pg.mkPen("#00FF00", width=1.5), name=tr("Left"))
        self.curve_r = self.fft_plot.plot(pen=pg.mkPen("#FFFF00", width=1.5), name=tr("Right"))

        # Fill between L and R to highlight differences
        self.fill_lr = pg.FillBetweenItem(self.curve_l, self.curve_r, brush=pg.mkBrush(255, 255, 255, 50))
        self.fft_plot.addItem(self.fill_lr)

        viz_layout.addWidget(self.fft_plot, stretch=2)

        # 2. Band-specific Correlation Plot
        self.corr_plot = pg.PlotWidget(title=tr("Band-specific Phase Correlation"))
        self.corr_plot.setLogMode(x=True, y=False)
        self.corr_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.corr_plot.setLabel("left", tr("Correlation"))
        self.corr_plot.showGrid(x=True, y=True, alpha=0.3)
        self.corr_plot.setXRange(np.log10(20), np.log10(20000))
        self.corr_plot.setYRange(-1.1, 1.1)

        self.curve_corr = self.corr_plot.plot(pen=pg.mkPen("#00FFFF", width=2))

        # Zero line for reference
        zero_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#888888", style=Qt.PenStyle.DashLine))
        self.corr_plot.addItem(zero_line)

        viz_layout.addWidget(self.corr_plot, stretch=1)

        main_layout.addLayout(viz_layout, stretch=3)

        # === Right: Metrics & Controls ===
        self.controls_container = QWidget()
        controls_layout = QVBoxLayout(self.controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Metrics Group
        metrics_group = QGroupBox(tr("Analysis Metrics"))
        metrics_grid = QGridLayout()

        font_val = QFont()
        font_val.setBold(True)
        font_val.setPointSize(12)

        # Balance
        metrics_grid.addWidget(QLabel(tr("L/R Balance:")), 0, 0)
        self.lbl_balance_val = QLabel("0.00 dB")
        self.lbl_balance_val.setFont(font_val)
        self.lbl_balance_val.setFixedWidth(100)
        self.lbl_balance_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_balance_jdg = QLabel(tr("Excellent"))
        self.lbl_balance_jdg.setFixedWidth(180)
        self.lbl_balance_jdg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metrics_grid.addWidget(self.lbl_balance_val, 0, 1)
        metrics_grid.addWidget(self.lbl_balance_jdg, 0, 2)

        # Frequency Match
        metrics_grid.addWidget(QLabel(tr("Freq Match:")), 1, 0)
        self.lbl_match_val = QLabel("0.0 %")
        self.lbl_match_val.setFont(font_val)
        self.lbl_match_val.setFixedWidth(100)
        self.lbl_match_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_match_jdg = QLabel("-")
        self.lbl_match_jdg.setFixedWidth(180)
        self.lbl_match_jdg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metrics_grid.addWidget(self.lbl_match_val, 1, 1)
        metrics_grid.addWidget(self.lbl_match_jdg, 1, 2)

        # Center Focus
        metrics_grid.addWidget(QLabel(tr("Center Focus:")), 2, 0)
        self.lbl_focus_val = QLabel("0.0 %")
        self.lbl_focus_val.setFont(font_val)
        self.lbl_focus_val.setFixedWidth(100)
        self.lbl_focus_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_focus_jdg = QLabel("-")
        self.lbl_focus_jdg.setFixedWidth(180)
        self.lbl_focus_jdg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metrics_grid.addWidget(self.lbl_focus_val, 2, 1)
        metrics_grid.addWidget(self.lbl_focus_jdg, 2, 2)

        # Phase Issues
        metrics_grid.addWidget(QLabel(tr("Phase Issues:")), 3, 0)
        self.lbl_phase_val = QLabel("0.0 %")
        self.lbl_phase_val.setFont(font_val)
        self.lbl_phase_val.setFixedWidth(100)
        self.lbl_phase_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_phase_jdg = QLabel("-")
        self.lbl_phase_jdg.setFixedWidth(180)
        self.lbl_phase_jdg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metrics_grid.addWidget(self.lbl_phase_val, 3, 1)
        metrics_grid.addWidget(self.lbl_phase_jdg, 3, 2)

        metrics_group.setLayout(metrics_grid)
        controls_layout.addWidget(metrics_group)

        # M/S Ratio Bar Group
        ms_group = QGroupBox(tr("M/S Ratio (Center Localization)"))
        ms_layout = QVBoxLayout()

        ms_labels = QHBoxLayout()
        ms_labels.addWidget(QLabel(tr("100% Side (Wide)")))
        ms_labels.addStretch()
        ms_labels.addWidget(QLabel(tr("100% Mid (Mono)")))
        ms_layout.addLayout(ms_labels)

        self.ms_bar = QProgressBar()
        self.ms_bar.setRange(0, 100)
        self.ms_bar.setValue(50)
        self.ms_bar.setTextVisible(False)
        self.ms_bar.setFixedHeight(20)
        self.ms_bar.setStyleSheet("QProgressBar::chunk { background-color: #3498db; }")
        ms_layout.addWidget(self.ms_bar)

        ms_group.setLayout(ms_layout)
        controls_layout.addWidget(ms_group)

        # Controls Group
        ctrl_group = QGroupBox(tr("Controls"))
        ctrl_vbox = QVBoxLayout()

        self.btn_toggle = QPushButton(tr("Start"))
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.clicked.connect(self.on_toggle)
        ctrl_vbox.addWidget(self.btn_toggle)

        self.chk_physical = QCheckBox(tr("Show Physical Units (dB/r/°)"))
        self.chk_physical.setChecked(False)
        ctrl_vbox.addWidget(self.chk_physical)

        ctrl_vbox.addWidget(QLabel(tr("Smoothing:")))
        self.slider_smooth = QSlider(Qt.Orientation.Horizontal)
        self.slider_smooth.setRange(0, 99)
        self.slider_smooth.setValue(int(self.module.smoothing_factor * 100))
        self.slider_smooth.valueChanged.connect(self.on_smooth_changed)
        ctrl_vbox.addWidget(self.slider_smooth)

        ctrl_group.setLayout(ctrl_vbox)
        controls_layout.addWidget(ctrl_group)

        controls_layout.addStretch()
        main_layout.addWidget(self.controls_container, stretch=1)

    def init_gang_error_tab(self):
        main_layout = QHBoxLayout(self.tab_gang_error)

        # === Left: 2D Plot ===
        self.gang_plot = pg.PlotWidget(title=tr("Volume Gang Error (L - R Balance over Average Level)"))
        self.gang_plot.setLabel("bottom", tr("Average Signal Level"), units="dBFS")
        self.gang_plot.setLabel("left", tr("L/R Balance (L - R)"), units="dB")
        self.gang_plot.showGrid(x=True, y=True, alpha=0.3)
        self.gang_plot.setXRange(-80, 0)
        self.gang_plot.setYRange(-3.0, 3.0)

        # Draw visual guidelines/bands
        # Excellent band: ±0.5 dB (Green)
        green_brush = pg.mkBrush(0, 255, 0, 20)  # semi-transparent green
        self.region_excellent = pg.LinearRegionItem(
            values=[-0.5, 0.5], orientation=pg.LinearRegionItem.Horizontal, brush=green_brush, movable=False
        )
        self.gang_plot.addItem(self.region_excellent)

        # Region -1.0 to 1.0 (Yellow, showing acceptable)
        yellow_brush = pg.mkBrush(255, 255, 0, 10)  # semi-transparent yellow
        self.region_good_top = pg.LinearRegionItem(
            values=[0.5, 1.0], orientation=pg.LinearRegionItem.Horizontal, brush=yellow_brush, movable=False
        )
        self.region_good_bottom = pg.LinearRegionItem(
            values=[-1.0, -0.5], orientation=pg.LinearRegionItem.Horizontal, brush=yellow_brush, movable=False
        )
        self.gang_plot.addItem(self.region_good_top)
        self.gang_plot.addItem(self.region_good_bottom)

        # Central ideal line (0 dB)
        center_line = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#888888", style=Qt.PenStyle.DashLine))
        self.gang_plot.addItem(center_line)

        # Data Curve and Scatter Points
        self.curve_gang = self.gang_plot.plot(
            pen=pg.mkPen("#3498db", width=2), symbol="o", symbolSize=6, symbolBrush=pg.mkBrush("#3498db")
        )

        main_layout.addWidget(self.gang_plot, stretch=3)

        # === Right: Controls ===
        controls_layout = QVBoxLayout()

        # Status Group
        status_group = QGroupBox(tr("Real-time Levels"))
        status_grid = QGridLayout()

        font_val = QFont()
        font_val.setBold(True)
        font_val.setPointSize(12)

        status_grid.addWidget(QLabel(tr("Left RMS:")), 0, 0)
        self.lbl_l_rms = QLabel("-inf dBFS")
        self.lbl_l_rms.setFont(font_val)
        self.lbl_l_rms.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_grid.addWidget(self.lbl_l_rms, 0, 1)

        status_grid.addWidget(QLabel(tr("Right RMS:")), 1, 0)
        self.lbl_r_rms = QLabel("-inf dBFS")
        self.lbl_r_rms.setFont(font_val)
        self.lbl_r_rms.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_grid.addWidget(self.lbl_r_rms, 1, 1)

        status_grid.addWidget(QLabel(tr("Current Balance:")), 2, 0)
        self.lbl_curr_bal = QLabel("0.00 dB")
        self.lbl_curr_bal.setFont(font_val)
        self.lbl_curr_bal.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_grid.addWidget(self.lbl_curr_bal, 2, 1)

        status_group.setLayout(status_grid)
        controls_layout.addWidget(status_group)

        # Logging Controls Group
        log_group = QGroupBox(tr("Logger Controls"))
        log_vbox = QVBoxLayout()

        self.btn_log_toggle = QPushButton(tr("Start Logging"))
        self.btn_log_toggle.setCheckable(True)
        self.btn_log_toggle.clicked.connect(self.on_log_toggle)
        log_vbox.addWidget(self.btn_log_toggle)

        self.btn_log_clear = QPushButton(tr("Clear Data"))
        self.btn_log_clear.clicked.connect(self.on_log_clear)
        log_vbox.addWidget(self.btn_log_clear)

        self.btn_log_export = QPushButton(tr("Export CSV"))
        self.btn_log_export.clicked.connect(self.on_log_export)
        log_vbox.addWidget(self.btn_log_export)

        log_group.setLayout(log_vbox)
        controls_layout.addWidget(log_group)

        # Settings Group
        settings_group = QGroupBox(tr("Settings"))
        settings_vbox = QVBoxLayout()

        settings_vbox.addWidget(QLabel(tr("Min Level for Logging (dBFS):")))
        self.lbl_thresh_val = QLabel("-60 dB")
        settings_vbox.addWidget(self.lbl_thresh_val)

        self.slider_thresh = QSlider(Qt.Orientation.Horizontal)
        self.slider_thresh.setRange(-80, -20)
        self.slider_thresh.setValue(int(self.module.log_threshold_db))
        self.slider_thresh.valueChanged.connect(self.on_thresh_changed)
        settings_vbox.addWidget(self.slider_thresh)

        settings_group.setLayout(settings_vbox)
        controls_layout.addWidget(settings_group)

        controls_layout.addStretch()
        main_layout.addLayout(controls_layout, stretch=1)

    def on_log_toggle(self, checked):
        self.module.is_logging = checked
        if checked:
            self.btn_log_toggle.setText(tr("Pause Logging"))
        else:
            self.btn_log_toggle.setText(tr("Start Logging"))

    def on_log_clear(self):
        with self.module._lock:
            self.module.gang_error_data.clear()
        self.curve_gang.setData([], [])

    def on_thresh_changed(self, val):
        self.module.log_threshold_db = float(val)
        self.lbl_thresh_val.setText(f"{val} dB")

    def on_log_export(self):
        with self.module._lock:
            if not self.module.gang_error_data:
                return
            gang_error_copy = self.module.gang_error_data.copy()

        filename, _ = QFileDialog.getSaveFileName(
            self, tr("Export Gang Error Data"), "gang_error.csv", "CSV Files (*.csv)"
        )
        if filename:
            try:
                import csv

                with open(filename, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Average Level (dBFS)", "L/R Balance (dB)"])
                    for avg_lvl in sorted(gang_error_copy.keys()):
                        writer.writerow([avg_lvl, gang_error_copy[avg_lvl]])
            except Exception as e:
                import logging

                logging.getLogger("MeasureLab").error(f"Failed to export CSV: {e}")

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.btn_toggle.setText(tr("Stop"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.btn_toggle.setText(tr("Start"))

    def on_smooth_changed(self, val):
        self.module.smoothing_factor = val / 100.0

    def update_display(self):
        # Read all shared values and make safe copies under lock
        with self.module._lock:
            current_l_db = self.module.current_l_db
            current_r_db = self.module.current_r_db
            current_diff_db = self.module.current_diff_db
            
            data_ready = self.module.data_ready
            if data_ready:
                self.module.data_ready = False
                freqs = self.module.freqs.copy()
                s_ll = self.module.s_ll.copy()
                s_rr = self.module.s_rr.copy()
                s_lr = self.module.s_lr.copy()
                balance_db = self.module.balance_db
                corr_raw = self.module.corr_raw
                freq_match = self.module.freq_match
                ms_ratio_db = self.module.ms_ratio_db
                center_focus = self.module.center_focus
                phase_issue = self.module.phase_issue
                phase_issue_deg = self.module.phase_issue_deg

            gang_error_data_copy = self.module.gang_error_data.copy() if self.module.gang_error_data else None

        # Always update real-time RMS levels for Tab 2 status
        self.lbl_l_rms.setText(f"{current_l_db:.1f} dBFS")
        self.lbl_r_rms.setText(f"{current_r_db:.1f} dBFS")
        self.lbl_curr_bal.setText(f"{current_diff_db:+.2f} dB")

        current_tab_idx = self.tabs.currentIndex()

        if current_tab_idx == 0:
            # Tab 1: Realtime Monitor
            if not data_ready:
                return

            # Skip DC (freq=0) for log plot
            valid = freqs > 0
            f_valid = freqs[valid]

            s_ll_v = s_ll[valid]
            s_rr_v = s_rr[valid]
            s_lr_v = s_lr[valid]

            epsilon = 1e-12

            # 1. Update FFT Plot
            # Convert to roughly dBFS (assuming 1.0 is full scale sine, power is 0.5)
            scale = 2.0 / (self.module.fft_size**2)
            db_l = 10 * np.log10(s_ll_v * scale + epsilon)
            db_r = 10 * np.log10(s_rr_v * scale + epsilon)

            self.curve_l.setData(f_valid, db_l)
            self.curve_r.setData(f_valid, db_r)

            # 2. Update Correlation Plot
            denom = np.sqrt(s_ll_v * s_rr_v) + epsilon
            corr = np.real(s_lr_v) / denom
            corr = np.clip(corr, -1.0, 1.0)
            self.curve_corr.setData(f_valid, corr)

            # 3. Update Metrics text
            self.lbl_balance_val.setText(f"{balance_db:+.2f} dB")
            if abs(balance_db) < 0.5:
                self.lbl_balance_jdg.setText(tr("Excellent"))
                self.lbl_balance_jdg.setStyleSheet("color: #00FF00;")
            elif abs(balance_db) < 3.0:
                self.lbl_balance_jdg.setText(tr("Good"))
                self.lbl_balance_jdg.setStyleSheet("color: #FFFF00;")
            else:
                self.lbl_balance_jdg.setText(tr("Unbalanced"))
                self.lbl_balance_jdg.setStyleSheet("color: #FF0000;")

            show_phys = self.chk_physical.isChecked()

            if show_phys:
                self.lbl_match_val.setText(f"r = {corr_raw:.3f}")
            else:
                self.lbl_match_val.setText(f"{freq_match:.1f} %")

            if freq_match > 95.0:
                self.lbl_match_jdg.setText(tr("Professional"))
                self.lbl_match_jdg.setStyleSheet("color: #00FF00;")
            elif freq_match > 80.0:
                self.lbl_match_jdg.setText(tr("Good"))
                self.lbl_match_jdg.setStyleSheet("color: #FFFF00;")
            else:
                self.lbl_match_jdg.setText(tr("Poor"))
                self.lbl_match_jdg.setStyleSheet("color: #FF0000;")

            if show_phys:
                self.lbl_focus_val.setText(f"{ms_ratio_db:+.1f} dB")
            else:
                self.lbl_focus_val.setText(f"{center_focus:.1f} %")

            if center_focus > 85.0:
                self.lbl_focus_jdg.setText(tr("Mono Compatible"))
                self.lbl_focus_jdg.setStyleSheet("color: #00FF00;")
            elif center_focus > 50.0:
                self.lbl_focus_jdg.setText(tr("Wide Stereo"))
                self.lbl_focus_jdg.setStyleSheet("color: #3498db;")
            else:
                self.lbl_focus_jdg.setText(tr("Phasey / Wide"))
                self.lbl_focus_jdg.setStyleSheet("color: #FFA500;")

            if show_phys:
                self.lbl_phase_val.setText(f"{phase_issue_deg:.1f}°")
            else:
                self.lbl_phase_val.setText(f"{phase_issue:.2f} %")

            if phase_issue < 1.0:
                self.lbl_phase_jdg.setText(tr("Negligible (Safe)"))
                self.lbl_phase_jdg.setStyleSheet("color: #00FF00;")
            elif phase_issue < 10.0:
                self.lbl_phase_jdg.setText(tr("Minor Issues"))
                self.lbl_phase_jdg.setStyleSheet("color: #FFFF00;")
            else:
                self.lbl_phase_jdg.setText(tr("Severe Issues"))
                self.lbl_phase_jdg.setStyleSheet("color: #FF0000;")

            # 4. Update M/S Bar
            self.ms_bar.setValue(int(center_focus))

        elif current_tab_idx == 1:
            # Tab 2: Volume Gang Error Logger
            if gang_error_data_copy:
                sorted_keys = sorted(gang_error_data_copy.keys())
                x_data = np.array(sorted_keys)
                y_data = np.array([gang_error_data_copy[k] for k in sorted_keys])
                self.curve_gang.setData(x_data, y_data)

    def update_compact_layout(self):
        compact = self.is_compact_mode()

        if hasattr(self, "controls_container"):
            self.controls_container.setHidden(compact)

        if hasattr(self, "tabs"):
            self.tabs.tabBar().setHidden(compact)
            if compact:
                self.tabs.setCurrentIndex(0)

        # Trigger parent window size adjustment
        win = self.window()
        if win:
            from PyQt6 import sip
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, lambda: win.adjustSize() if not sip.isdeleted(win) else None)
