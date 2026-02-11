import queue

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.core.spectrum_processor import SpectrumProcessor
from src.measurement_modules.base import MeasurementModule
from src.core.audio_engine import AudioEngine


class SpectrumAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 4096
        # Store stereo data: (frames, 2)
        self.input_data = np.zeros((self.buffer_size, 2))
        self.write_head = 0
        self.audio_queue = queue.Queue()

        # Analysis parameters
        self.window_type = "hanning"
        self.averaging = 0.0  # 0.0 to 0.95
        self.peak_hold = False
        self.octave_smoothing = "None"  # None, 1/1, 1/3, 1/6, 1/12, 1/24
        self.analysis_mode = "Spectrum"  # 'Spectrum', 'Cross Spectrum'
        self.channel_mode = "Average"  # 'Left', 'Right', 'Average', 'Dual'
        self.multitaper_enabled = False
        self.display_unit = "dBFS"  # 'dBFS', 'dBV', 'dB SPL'
        self.weighting = "Z"  # 'Z', 'A', 'C'

        self.callback_id = None

        # Processor
        self.processor = SpectrumProcessor()

    @property
    def name(self) -> str:
        return "Spectrum Analyzer"

    @property
    def description(self) -> str:
        return "Real-time frequency spectrum analysis."

    def get_widget(self):
        return SpectrumAnalyzerWidget(self)

    def reset(self):
        self.processor.reset()

    def set_buffer_size(self, size):
        self.buffer_size = size
        self.input_data = np.zeros((self.buffer_size, 2))
        self.write_head = 0
        self.reset()

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self.reset()
        self.input_data = np.zeros((self.buffer_size, 2))
        self.write_head = 0

        # Clear queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        def callback(indata, outdata, frames, time, status):
            if status:
                print(status)

            # Shift buffer and append new data
            # We always capture 2 channels now if available
            if indata.shape[1] >= 2:
                new_data = indata[:, :2].copy()
            else:
                # If mono, duplicate to stereo for simplicity or handle gracefully
                new_data = np.column_stack((indata[:, 0], indata[:, 0]))

            self.audio_queue.put(new_data)
            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def process_queue(self):
        # Threshold for switching to "Snapshot / Slow" mode
        LARGE_BUFFER_THRESHOLD = 500000

        while not self.audio_queue.empty():
            try:
                new_data = self.audio_queue.get_nowait()
            except queue.Empty:
                break

            if self.buffer_size >= LARGE_BUFFER_THRESHOLD:
                # --- Slow / Snapshot Mode ---
                # Fill buffer linearly, then stop accepting data until processed (write_head reset)

                # If buffer is already "full" (waiting for processing), do nothing
                if self.write_head >= self.buffer_size:
                    continue

                # Calculate how much space is left
                space_left = self.buffer_size - self.write_head
                to_write = min(len(new_data), space_left)

                if to_write > 0:
                    self.input_data[self.write_head : self.write_head + to_write] = new_data[:to_write]
                    self.write_head += to_write
            else:
                # --- Normal Rolling Mode ---
                # Efficient ring buffer logic (like Oscilloscope)
                n_frames = len(new_data)
                if n_frames > self.buffer_size:
                    # Just take the last part
                    self.input_data[:] = new_data[-self.buffer_size :]
                    self.write_head = 0
                else:
                    # Wrapped write
                    idx = self.write_head
                    end_idx = idx + n_frames
                    if end_idx <= self.buffer_size:
                        self.input_data[idx:end_idx] = new_data
                    else:
                        # Split
                        part1_len = self.buffer_size - idx
                        self.input_data[idx:] = new_data[:part1_len]
                        self.input_data[: n_frames - part1_len] = new_data[part1_len:]

                    self.write_head = (idx + n_frames) % self.buffer_size

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def get_current_buffer(self):
        # Threshold for switching to "Snapshot / Slow" mode
        LARGE_BUFFER_THRESHOLD = 500000

        if self.buffer_size >= LARGE_BUFFER_THRESHOLD:
            # Snapshot Mode Logic
            if self.write_head < self.buffer_size:
                # Buffer not full yet, wait
                return None

            # Buffer full, take snapshot and reset
            data = self.input_data.copy()

            # Reset write head to start new capture
            self.write_head = 0
            return data
        else:
            # Normal Rolling Mode
            idx = self.write_head
            if idx == 0:
                data = self.input_data.copy()
            else:
                data = np.concatenate(
                    (self.input_data[idx:], self.input_data[:idx]),
                    axis=0,
                )
            return data

    def compute_spectrum(self):
        data = self.get_current_buffer()
        if data is None:
            return None

        config = {
            "window_type": self.window_type,
            "analysis_mode": self.analysis_mode,
            "channel_mode": self.channel_mode,
            "multitaper_enabled": self.multitaper_enabled,
            "averaging": self.averaging,
            "weighting": self.weighting,
            "display_unit": self.display_unit,
            "peak_hold": self.peak_hold,
            "octave_smoothing": self.octave_smoothing,
        }

        input_offset_db = self.audio_engine.calibration.get_input_offset_db()
        spl_offset_db = self.audio_engine.calibration.get_spl_offset_db()

        return self.processor.process(data, self.audio_engine.sample_rate, config, (input_offset_db, spl_offset_db))


class SpectrumAnalyzerWidget(QWidget):
    def __init__(self, module: SpectrumAnalyzer):
        super().__init__()
        self.module = module
        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.setInterval(30)

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Controls ---
        controls_group = QGroupBox(tr("Analysis Settings"))
        main_controls_layout = QVBoxLayout()

        # Row 1: Basic Controls
        row1_layout = QHBoxLayout()

        # Start/Stop
        self.toggle_btn = QPushButton(tr("Start Analysis"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle)

        self.toggle_btn.setStyleSheet(
            "QPushButton { background-color: #ccffcc; color: black; } QPushButton:checked { background-color: #ffcccc; color: black; }"
        )

        row1_layout.addWidget(self.toggle_btn)

        # Mode Selection
        row1_layout.addWidget(QLabel(tr("Mode:")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("Spectrum"), "Spectrum")
        self.mode_combo.addItem(tr("PSD"), "PSD")
        self.mode_combo.addItem(tr("Cross Spectrum"), "Cross Spectrum")

        # Set initial selection
        index = self.mode_combo.findData(self.module.analysis_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)

        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        row1_layout.addWidget(self.mode_combo)

        # Channel Selection
        row1_layout.addWidget(QLabel(tr("Channel:")))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Left", "Right", "Average", "Dual"])
        self.channel_combo.setCurrentText(self.module.channel_mode)
        self.channel_combo.currentTextChanged.connect(self.on_channel_changed)
        row1_layout.addWidget(self.channel_combo)

        # FFT Size
        row1_layout.addWidget(QLabel(tr("FFT Size:")))
        self.fft_combo = QComboBox()
        self.fft_combo.addItems(
            [
                "1024",
                "2048",
                "4096",
                "8192",
                "16384",
                "32768",
                "65536",
                "131072",
                "262144",
                "1M (Slow)",
                "2M (Slow)",
                "4M (Slow)",
            ]
        )
        self.fft_combo.setCurrentText(str(self.module.buffer_size))
        self.fft_combo.currentTextChanged.connect(self.on_fft_size_changed)
        row1_layout.addWidget(self.fft_combo)

        # Window Selection
        row1_layout.addWidget(QLabel(tr("Window:")))
        self.window_combo = QComboBox()
        self.window_combo.addItems(fft_manager.get_available_windows())
        # Set initial if valid, else default to hanning (hann)
        idx = self.window_combo.findText(self.module.window_type)
        if idx >= 0:
            self.window_combo.setCurrentIndex(idx)
        else:
             # Fallback for "hanning" vs "hann" if needed
             if self.module.window_type == "hanning":
                 idx = self.window_combo.findText("hann")
                 if idx >= 0:
                     self.window_combo.setCurrentIndex(idx)

        self.window_combo.currentTextChanged.connect(self.on_window_changed)
        row1_layout.addWidget(self.window_combo)

        # Weighting Selection
        row1_layout.addWidget(QLabel(tr("Weighting:")))
        self.weighting_combo = QComboBox()
        self.weighting_combo.addItems(["Z", "A", "C"])
        self.weighting_combo.currentTextChanged.connect(self.on_weighting_changed)
        row1_layout.addWidget(self.weighting_combo)

        # Unit Selection (Replaces Physical Units Checkbox)
        row1_layout.addWidget(QLabel(tr("Unit:")))
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dBFS", "dBV", "dB SPL"])
        self.unit_combo.setCurrentText(self.module.display_unit)
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)
        row1_layout.addWidget(self.unit_combo)

        main_controls_layout.addLayout(row1_layout)

        # Row 2: Advanced Controls
        row2_layout = QHBoxLayout()

        # Smoothing
        row2_layout.addWidget(QLabel(tr("Smoothing:")))
        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), "None")
        self.smooth_combo.addItem(tr("1/1 Octave"), "1/1 Octave")
        self.smooth_combo.addItem(tr("1/3 Octave"), "1/3 Octave")
        self.smooth_combo.addItem(tr("1/6 Octave"), "1/6 Octave")
        self.smooth_combo.addItem(tr("1/12 Octave"), "1/12 Octave")
        self.smooth_combo.addItem(tr("1/24 Octave"), "1/24 Octave")

        index = self.smooth_combo.findData(self.module.octave_smoothing)
        if index >= 0:
            self.smooth_combo.setCurrentIndex(index)

        self.smooth_combo.currentIndexChanged.connect(self.on_smooth_changed)
        row2_layout.addWidget(self.smooth_combo)

        # Averaging
        self.avg_label = QLabel(tr("Avg: 0%"))
        row2_layout.addWidget(self.avg_label)
        self.avg_slider = QSlider(Qt.Orientation.Horizontal)
        self.avg_slider.setRange(0, 99)  # Allow up to 99% for heavy averaging
        self.avg_slider.setValue(0)
        self.avg_slider.setFixedWidth(100)
        self.avg_slider.valueChanged.connect(self.on_avg_changed)
        row2_layout.addWidget(self.avg_slider)

        # Multitaper
        self.multitaper_check = QCheckBox(tr("Multitaper"))
        self.multitaper_check.toggled.connect(self.on_multitaper_changed)
        row2_layout.addWidget(self.multitaper_check)

        # Peak Hold
        self.peak_check = QCheckBox(tr("Peak Hold"))
        self.peak_check.toggled.connect(self.on_peak_changed)
        row2_layout.addWidget(self.peak_check)

        # Clear Peak
        self.clear_peak_btn = QPushButton(tr("Clear Peak"))
        self.clear_peak_btn.clicked.connect(self.on_clear_peak)
        row2_layout.addWidget(self.clear_peak_btn)

        main_controls_layout.addLayout(row2_layout)

        # Row 3: Calibration (Removed Physical Units from here)
        # row3_layout = QHBoxLayout()
        # row3_layout.addStretch()
        # main_controls_layout.addLayout(row3_layout)

        controls_group.setLayout(main_controls_layout)
        layout.addWidget(controls_group)

        # --- Info Display ---
        info_layout = QHBoxLayout()

        # Overall Value
        self.overall_label = QLabel(tr("Overall: -- dB"))
        self.overall_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ff00;")
        info_layout.addWidget(self.overall_label)

        # Cursor Value
        self.cursor_label = QLabel(tr("Cursor: -- Hz, -- dB"))
        self.cursor_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ffff;")
        info_layout.addWidget(self.cursor_label)

        info_layout.addStretch()
        layout.addLayout(info_layout)

        # --- Plot ---
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", tr("Magnitude"), units="dB")
        self.plot_widget.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_widget.setLogMode(x=True, y=False)
        self.plot_widget.setYRange(-120, 0)
        self.plot_widget.showGrid(x=True, y=True)

        # Custom Axis Ticks
        axis = self.plot_widget.getPlotItem().getAxis("bottom")
        ticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        # Since setLogMode(x=True) is used, the view coordinates are log10(freq).
        # We need to specify ticks at log positions.
        ticks_log = [(np.log10(t), str(t) if t < 1000 else f"{t / 1000:.0f}k") for t in ticks]
        axis.setTicks([ticks_log])

        # Set Range (log domain)
        self.plot_widget.setXRange(np.log10(20), np.log10(20000))

        # Crosshair
        self.v_line = pg.InfiniteLine(angle=90, movable=False)
        self.h_line = pg.InfiniteLine(angle=0, movable=False)
        self.plot_widget.addItem(self.v_line, ignoreBounds=True)
        self.plot_widget.addItem(self.h_line, ignoreBounds=True)

        # Mouse movement proxy
        self.proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)

        # Curves
        self.peak_curve = self.plot_widget.plot(pen=pg.mkPen("r", width=1, style=Qt.PenStyle.DashLine))
        self.plot_curve = self.plot_widget.plot(pen="y", name="Main")
        self.plot_curve_2 = self.plot_widget.plot(
            pen="g", name="Secondary"
        )

        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

    def format_si(self, value, unit):
        if value == 0:
            return f"0.0 {unit}"

        exponent = int(np.floor(np.log10(abs(value)) / 3) * 3)
        exponent = max(min(exponent, 9), -15)

        scaled_value = value / (10**exponent)

        prefixes = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G"}

        prefix = prefixes.get(exponent, "")
        return f"{scaled_value:.3g} {prefix}{unit}"

    def mouse_moved(self, evt):
        pos = evt[0]
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)

            x = mouse_point.x()
            y = mouse_point.y()

            # x is log10(freq)
            freq = 10**x

            unit_db = self.module.display_unit
            unit_linear = ""

            if self.module.display_unit == "dBV":
                unit_linear = "V"
            elif self.module.display_unit == "dB SPL":
                unit_linear = "Pa"

            if self.module.analysis_mode == "PSD":
                unit_db += "/√Hz"
                if unit_linear:
                    unit_linear += "/√Hz"

            # Calculate linear value
            linear_val = 10 ** (y / 20)

            # Format linear value
            if self.module.display_unit == "dB SPL":
                # For SPL, y is dB SPL. Linear is 10^(y/20) * 20uPa.
                val_pa = (10 ** (y / 20)) * 20e-6
                linear_str = self.format_si(val_pa, "Pa")
                cursor_text = f"Cursor: {freq:.1f} Hz, {y:.1f} {unit_db} ({linear_str})"
            elif self.module.display_unit == "dBV":
                linear_str = self.format_si(linear_val, unit_linear)
                cursor_text = f"Cursor: {freq:.1f} Hz, {y:.1f} {unit_db} ({linear_str})"
            else:  # dBFS
                cursor_text = f"Cursor: {freq:.1f} Hz, {y:.1f} {unit_db} ({linear_val:.4g})"

            self.cursor_label.setText(cursor_text)
            self.v_line.setPos(x)
            self.h_line.setPos(y)

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop Analysis"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start Analysis"))

    def on_mode_changed(self, index):
        val = self.mode_combo.itemData(index)
        if val is None:
            return
        self.module.analysis_mode = val
        self.module.reset()
        self.peak_curve.setData([], [])

        # Disable channel selection in Cross Spectrum mode?
        # Cross Spectrum inherently uses L and R.
        if val == "Cross Spectrum":
            self.channel_combo.setEnabled(False)
        else:
            self.channel_combo.setEnabled(True)

        # Update Y-axis label
        unit = self.module.display_unit
        if val == "PSD":
            unit += "/√Hz"
        self.plot_widget.setLabel("left", "Magnitude", units=unit)

    def on_channel_changed(self, val):
        self.module.channel_mode = val
        self.module.reset()
        self.peak_curve.setData([], [])

    def on_fft_size_changed(self, val):
        if "1M" in val:
            size = 1048576
        elif "2M" in val:
            size = 2097152
        elif "4M" in val:
            size = 4194304
        else:
            size = int(val)
        self.module.set_buffer_size(size)

    def on_window_changed(self, val):
        self.module.window_type = val

    def on_weighting_changed(self, val):
        self.module.weighting = val
        self.module.reset()
        self.peak_curve.setData([], [])

    def on_smooth_changed(self, index):
        val = self.smooth_combo.itemData(index)
        if val is None:
            return
        self.module.octave_smoothing = val

    def on_avg_changed(self, val):
        self.module.averaging = val / 100.0
        self.avg_label.setText(tr("Avg: {}%").format(val))

    def on_multitaper_changed(self, checked):
        self.module.multitaper_enabled = checked
        # Disable window selection if multitaper is on (it uses its own windows)
        self.window_combo.setEnabled(not checked)

    def on_peak_changed(self, checked):
        self.module.peak_hold = checked
        if not checked:
            self.module.reset() # This resets everything including average, but maybe peak toggle should only clear peak?
            # Original code only cleared peak.
            # self.module._peak_magnitude = None
            # Processor reset clears everything.
            # I should strictly clear peak only, but SpectrumProcessor doesn't expose it.
            # But the result returned will have None for peak_magnitude if peak_hold is False.
            # So just toggling peak_hold in module is enough for future updates.
            # But for visual feedback we might want to clear curve immediately.
            self.peak_curve.setData([], [])

    def on_clear_peak(self):
        # We need to clear peak state in processor.
        self.module.reset() # This clears averages too!
        # Ideally we want `clear_peak()` in module/processor.
        # But reset() is safe enough for now.
        self.peak_curve.setData([], [])

    def on_unit_changed(self, val):
        self.module.display_unit = val
        unit = val
        if self.module.analysis_mode == "PSD":
            unit += "/√Hz"
        self.plot_widget.setLabel("left", "Magnitude", units=unit)
        self.module.reset()
        self.peak_curve.setData([], [])

    def update_plot(self):
        if not self.module.is_running:
            return

        # Process audio queue
        self.module.process_queue()

        # Compute Spectrum
        results = self.module.compute_spectrum()

        if results is None:
            return

        freqs = results["freqs"]
        magnitude = results["magnitude"]
        peak_mags = results["peak_magnitude"]
        overall_weighted_db = results["overall_weighted_db"]
        smoothed_freqs = results["smoothed_freqs"]
        smoothed_mags = results["smoothed_magnitude"]
        smoothed_peak_mags = results["smoothed_peak_magnitude"]

        # Update Labels
        unit_suffix = ""
        if self.module.weighting == "A":
            unit_suffix = "A"
        elif self.module.weighting == "C":
            unit_suffix = "C"
        elif self.module.weighting == "Z":
            unit_suffix = "Z"

        if self.module.display_unit == "dB SPL":
            unit_display = f"dB SPL({unit_suffix})"
        elif self.module.display_unit == "dBV":
            unit_display = f"dBV({unit_suffix})"
        else:
            unit_display = f"dBFS({unit_suffix})"

        self.overall_label.setText(f"Overall: {overall_weighted_db:.1f} {unit_display}")

        # Choose data to plot (Smoothed vs Raw)
        if smoothed_freqs is not None:
            plot_freqs = smoothed_freqs
            plot_mags = smoothed_mags
            if peak_mags is not None and smoothed_peak_mags is not None:
                plot_peak_mags = smoothed_peak_mags
            else:
                plot_peak_mags = None
        else:
            # Exclude DC or 0Hz for log plot if needed, but pyqtgraph handles it usually or we shift it.
            # In previous code: plot_freqs = freqs[1:], plot_mags = magnitude[1:]
            if len(freqs) > 1:
                plot_freqs = freqs[1:]
                plot_mags = magnitude[1:]
                if peak_mags is not None:
                    plot_peak_mags = peak_mags[1:]
                else:
                    plot_peak_mags = None
            else:
                plot_freqs = freqs
                plot_mags = magnitude
                plot_peak_mags = peak_mags

        # Update curves
        # When setLogMode(x=True) is active, we must pass LINEAR x values to setData.
        # pyqtgraph handles the log conversion.
        plot_freqs_linear = plot_freqs + 1e-12  # Avoid exact 0

        # Handle Dual Mode Plotting
        if self.module.analysis_mode in ["Spectrum", "PSD"] and self.module.channel_mode == "Dual":
            # plot_mags should be (N, 2)
            if plot_mags.ndim == 2 and plot_mags.shape[1] >= 2:
                # Curve 1 (Left) - Green
                self.plot_curve.setData(plot_freqs_linear, plot_mags[:, 0], pen="g")
                # Curve 2 (Right) - Red
                self.plot_curve_2.setData(plot_freqs_linear, plot_mags[:, 1], pen="r")
            else:
                # Fallback
                self.plot_curve.setData(plot_freqs_linear, plot_mags, pen="y")
                self.plot_curve_2.setData([], [])
        else:
            # Single Curve
            # Ensure 1D
            if plot_mags.ndim == 2:
                plot_mags = plot_mags[:, 0]

            self.plot_curve.setData(plot_freqs_linear, plot_mags, pen="y")
            self.plot_curve_2.setData([], [])

        if plot_peak_mags is not None:
            if plot_peak_mags.ndim == 2:
                plot_peak_mags = plot_peak_mags[:, 0]
            self.peak_curve.setData(plot_freqs_linear, plot_peak_mags)
        else:
            self.peak_curve.setData([], [])

    def apply_theme(self, theme_name):
        # If theme_name is 'system', resolve it
        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            # Dark Theme: Darker colors, White text
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
                "QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
                "QPushButton:hover { background-color: #388e3c; }"
                "QPushButton:checked:hover { background-color: #d32f2f; }"
            )
            self.overall_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ff00;")
            self.cursor_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ffff;")
        else:
            # Light Theme: Pastel colors, Black text
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #ccffcc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
                "QPushButton:checked { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
                "QPushButton:hover { background-color: #bbfebb; }"
                "QPushButton:checked:hover { background-color: #ffbbbb; }"
            )
            self.overall_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #008800;")
            self.cursor_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #0000aa;")

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())
