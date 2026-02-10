
import threading

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTransform, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.analysis import get_cached_window
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.fft_manager import fft_manager
from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT


class Spectrogram(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False

        # Parameters
        self.fft_size = 2048
        self.overlap = 0.5
        self.window_type = "hann"
        self.channel_mode = "Left"  # 'Left', 'Right', 'Average'
        self.history_length = 500  # Number of time steps to keep
        self.sweep_speed_index = 0  # 0: Fast, 1: Medium, 2: Slow, 3: Meteor
        self.min_freq = 0
        self.max_freq = 20000  # Default, will be updated by UI or sample rate

        # State
        self.input_buffer = np.zeros(self.fft_size)  # For overlap processing
        self.spectrogram_buffer = np.full((self.history_length, self.fft_size // 2 + 1), -120.0)
        self.spectrogram_ptr = 0
        self.callback_id = None

        # Accumulator for Sweep Speed
        self.accumulator = None
        self.acc_count = 0
        self.mag_buffer = None

        # Ring buffer for incoming audio
        self.audio_buffer = np.zeros((self.fft_size * 2, 2))  # Keep enough for overlap
        self.audio_buffer_pos = 0
        self.output_buffer = None
        self.buffer_lock = threading.Lock()

    @property
    def name(self) -> str:
        return "Spectrogram"

    @property
    def description(self) -> str:
        return "Time-frequency analysis (Spectrogram)."



    def get_widget(self):
        return SpectrogramWidget(self)

    def set_fft_size(self, size):
        self.fft_size = size
        self.reset_buffers()

    def reset_buffers(self):
        with self.buffer_lock:
            self.spectrogram_buffer = np.full((self.history_length, self.fft_size // 2 + 1), -120.0)
            self.spectrogram_ptr = 0
            self.audio_buffer = np.zeros((self.fft_size * 2, 2))
            self.audio_buffer_pos = 0
            self.accumulator = None
            self.acc_count = 0
            self.output_buffer = None
            self.mag_buffer = None

    def start_analysis(self):
        if self.is_running:
            return
        self.is_running = True
        self.reset_buffers()
        self.callback_id = self.audio_engine.register_callback(self._callback)

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def get_latest_samples(self, n_samples):
        """Returns the latest n_samples from the ring buffer."""
        with self.buffer_lock:
            buffer_len = len(self.audio_buffer)
            if n_samples > buffer_len:
                n_samples = buffer_len

            end_pos = self.audio_buffer_pos
            start_pos = end_pos - n_samples

            # Always use output_buffer to ensure thread safety (avoid returning a view)
            if self.output_buffer is None or self.output_buffer.shape[0] != n_samples:
                self.output_buffer = np.zeros((n_samples, 2))

            if start_pos >= 0:
                self.output_buffer[:] = self.audio_buffer[start_pos:end_pos]
            else:
                # Wrap around
                p1 = self.audio_buffer[start_pos:]
                p2 = self.audio_buffer[:end_pos]

                self.output_buffer[: len(p1)] = p1
                self.output_buffer[len(p1) :] = p2

            return self.output_buffer

    def add_spectrum(self, mag_db):
        """Adds a new spectrum frame to the circular buffer."""
        # Ensure shape match if possible, but for performance assume caller is correct or numpy will raise
        self.spectrogram_buffer[self.spectrogram_ptr] = mag_db
        self.spectrogram_ptr = (self.spectrogram_ptr + 1) % self.history_length

    def _callback(self, indata, outdata, frames, time, status):
        with self.buffer_lock:
            # Write to ring buffer
            # audio_buffer_pos points to the next write index

            buffer_len = len(self.audio_buffer)

            if frames >= buffer_len:
                # Just overwrite the whole buffer with the last part of indata
                if indata.shape[1] >= 2:
                    self.audio_buffer[:] = indata[-buffer_len:, :2]
                else:
                    self.audio_buffer[:, 0] = indata[-buffer_len:, 0]
                    self.audio_buffer[:, 1] = indata[-buffer_len:, 0]
                self.audio_buffer_pos = 0
            else:
                end_pos = self.audio_buffer_pos + frames
                if end_pos <= buffer_len:
                    # No wrap
                    if indata.shape[1] >= 2:
                        self.audio_buffer[self.audio_buffer_pos:end_pos] = indata[:, :2]
                    else:
                        self.audio_buffer[self.audio_buffer_pos:end_pos, 0] = indata[:, 0]
                        self.audio_buffer[self.audio_buffer_pos:end_pos, 1] = indata[:, 0]
                else:
                    # Wrap around
                    first_chunk = buffer_len - self.audio_buffer_pos
                    second_chunk = frames - first_chunk

                    if indata.shape[1] >= 2:
                        self.audio_buffer[self.audio_buffer_pos:] = indata[:first_chunk, :2]
                        self.audio_buffer[:second_chunk] = indata[first_chunk:, :2]
                    else:
                        self.audio_buffer[self.audio_buffer_pos:, 0] = indata[:first_chunk, 0]
                        self.audio_buffer[self.audio_buffer_pos:, 1] = indata[:first_chunk, 0]

                        self.audio_buffer[:second_chunk, 0] = indata[first_chunk:, 0]
                        self.audio_buffer[:second_chunk, 1] = indata[first_chunk:, 0]

                self.audio_buffer_pos = (self.audio_buffer_pos + frames) % buffer_len

        outdata.fill(0)


class SpectrogramWidget(QWidget):
    def __init__(self, module: Spectrogram):
        super().__init__()
        self.module = module
        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_spectrogram)
        self.timer.setInterval(30)  # ~30 FPS

    def closeEvent(self, event: QCloseEvent):
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)

    def init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(self._init_controls())
        layout.addWidget(self._init_plot())
        self.setLayout(layout)

    def _init_controls(self) -> QGroupBox:
        controls_group = QGroupBox(tr("Settings"))
        controls_layout = QHBoxLayout()

        # Start/Stop
        self.toggle_btn = QPushButton(tr("Start"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle)

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())
        else:
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)

        controls_layout.addWidget(self.toggle_btn)

        # Channel
        controls_layout.addWidget(QLabel(tr("Channel:")))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Left", "Right", "Average"])
        self.channel_combo.currentTextChanged.connect(self.on_channel_changed)
        controls_layout.addWidget(self.channel_combo)

        # FFT Size
        controls_layout.addWidget(QLabel(tr("FFT Size:")))
        self.fft_combo = QComboBox()
        self.fft_combo.addItems(["512", "1024", "2048", "4096", "8192"])
        self.fft_combo.setCurrentText(str(self.module.fft_size))
        self.fft_combo.currentTextChanged.connect(self.on_fft_changed)
        controls_layout.addWidget(self.fft_combo)

        # Window
        controls_layout.addWidget(QLabel(tr("Window:")))
        self.window_combo = QComboBox()
        self.window_combo.addItems(fft_manager.get_available_windows())
        self.window_combo.setCurrentText(self.module.window_type)
        self.window_combo.currentTextChanged.connect(self.on_window_changed)
        controls_layout.addWidget(self.window_combo)

        # Colormap
        controls_layout.addWidget(QLabel(tr("Colormap:")))
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(["viridis", "plasma", "inferno", "magma", "cividis", "turbo"])
        self.cmap_combo.currentTextChanged.connect(self.on_cmap_changed)
        controls_layout.addWidget(self.cmap_combo)

        # Sweep Speed
        controls_layout.addWidget(QLabel(tr("Speed:")))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems([tr("Fast (Realtime)"), tr("Medium (1m)"), tr("Slow (5m)"), tr("Meteor (10m)")])
        self.speed_combo.currentIndexChanged.connect(self.on_speed_changed)
        controls_layout.addWidget(self.speed_combo)

        # Min Freq
        controls_layout.addWidget(QLabel(tr("Min Freq:")))
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(0, 96000)
        self.min_freq_spin.setValue(int(self.module.min_freq))
        self.min_freq_spin.setSuffix(" Hz")
        self.min_freq_spin.valueChanged.connect(self.on_freq_range_changed)
        controls_layout.addWidget(self.min_freq_spin)

        # Max Freq
        controls_layout.addWidget(QLabel(tr("Max Freq:")))
        self.max_freq_spin = QSpinBox()
        self.max_freq_spin.setRange(0, 96000)
        self.max_freq_spin.setValue(int(self.module.max_freq))
        self.max_freq_spin.setSuffix(" Hz")
        self.max_freq_spin.valueChanged.connect(self.on_freq_range_changed)
        controls_layout.addWidget(self.max_freq_spin)

        controls_group.setLayout(controls_layout)
        return controls_group

    def _init_plot(self) -> pg.GraphicsLayoutWidget:
        # We use a GraphicsLayoutWidget to hold the Plot and Histogram
        self.win = pg.GraphicsLayoutWidget()

        # Plot Item
        self.plot = self.win.addPlot(title=tr("Spectrogram"))
        self.plot.setLabel("left", tr("Frequency"), units="Hz")
        self.plot.setLabel("bottom", tr("Time"), units="frames")

        # Image Item
        # We use two images to render the circular buffer without copying
        self.img_old = pg.ImageItem()  # Older data (right side of pointer in buffer)
        self.img_new = pg.ImageItem()  # Newer data (left side of pointer in buffer)
        self.plot.addItem(self.img_old)
        self.plot.addItem(self.img_new)

        # Histogram (Colormap Control)
        self.hist = pg.HistogramLUTItem()
        self.hist.setImageItem(self.img_old)  # Control the first image
        self.win.addItem(self.hist)

        # Sync second image
        self.hist.sigLevelsChanged.connect(lambda: self.img_new.setLevels(self.hist.getLevels()))
        self.hist.sigLookupTableChanged.connect(lambda: self.img_new.setLookupTable(self.hist.gradient.getLookupTable(512)))

        # Set default colormap
        self.hist.gradient.loadPreset("viridis")
        self.hist.setLevels(-120, 0)  # Default dB range

        return self.win

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start"))

    def on_channel_changed(self, val):
        self.module.channel_mode = val

    def on_fft_changed(self, val):
        self.module.set_fft_size(int(val))
        # Update Image Transform if needed (scale)
        # We will handle scaling in update_spectrogram

    def on_window_changed(self, val):
        self.module.window_type = val

    def on_cmap_changed(self, val):
        self.hist.gradient.loadPreset(val)

    def on_speed_changed(self, idx):
        self.module.sweep_speed_index = idx
        # Reset accumulator on speed change to avoid mixing
        self.module.accumulator = None
        self.module.acc_count = 0

    def on_freq_range_changed(self):
        self.module.min_freq = self.min_freq_spin.value()
        self.module.max_freq = self.max_freq_spin.value()
        self.plot.setYRange(self.module.min_freq, self.module.max_freq)

    def update_spectrogram(self):
        if not self.module.is_running:
            return

        # Get latest data from buffer
        # We take the last fft_size samples
        raw_data = self.module.get_latest_samples(self.module.fft_size)

        # Select Channel
        if self.module.channel_mode == "Left":
            sig = raw_data[:, 0]
        elif self.module.channel_mode == "Right":
            sig = raw_data[:, 1]
        else:
            sig = np.mean(raw_data, axis=1)

        # Determine Target Frames based on Speed
        # Update rate is 30ms.
        # Fast: Update every frame (1)
        # Medium: 1 min = 60s. 500 pixels. 0.12s/pixel. 30ms -> 4 frames.
        # Slow: 5 min = 300s. 0.6s/pixel. 30ms -> 20 frames.
        # Meteor: 10 min = 600s. 1.2s/pixel. 30ms -> 40 frames.

        target_frames = 1
        if self.module.sweep_speed_index == 1:
            target_frames = 4
        elif self.module.sweep_speed_index == 2:
            target_frames = 20
        elif self.module.sweep_speed_index == 3:
            target_frames = 40

        # Windowing
        window = get_cached_window(self.module.window_type, len(sig))
        sig_win = sig * window

        # Window Correction Factor (Coherent Gain)
        win_correction = 1.0 / np.mean(window)

        # FFT
        fft_res = fft_manager.rfft(sig_win)

        # Optimized: Use pre-allocated buffer
        if self.module.mag_buffer is None or self.module.mag_buffer.shape != fft_res.shape:
            self.module.mag_buffer = np.zeros(fft_res.shape, dtype=fft_res.real.dtype)

        mag = self.module.mag_buffer
        np.abs(fft_res, out=mag)

        # Normalize
        # Optimized in-place normalization
        mag *= (2.0 * win_correction) / len(sig)

        # Convert to dB
        # In-place optimization to save memory bandwidth
        with np.errstate(divide="ignore"):
            np.add(mag, 1e-12, out=mag)
            np.log10(mag, out=mag)
            np.multiply(mag, 20, out=mag)
            mag_db = mag

        # --- Accumulation Logic ---
        if self.module.accumulator is None or self.module.accumulator.shape != mag_db.shape:
            if target_frames > 1:
                self.module.accumulator = mag_db.copy()
            else:
                self.module.accumulator = mag_db
            self.module.acc_count = 1
        else:
            # Max Hold Accumulation
            np.maximum(self.module.accumulator, mag_db, out=self.module.accumulator)
            self.module.acc_count += 1

        if self.module.acc_count < target_frames:
            return  # Wait for more data

        # Push to Spectrogram
        final_mag_db = self.module.accumulator
        self.module.accumulator = None  # Reset
        self.module.acc_count = 0

        # Update Spectrogram Data
        self.module.add_spectrum(final_mag_db)

        # Update Image (Circular Buffer Visualization)
        # buffer: [ 0 1 2 ... ptr-1 | ptr ... N ]
        # Time order: ptr (Oldest) -> ... -> N -> 0 -> ... -> ptr-1 (Newest)
        # We render [ptr:] at X=0 (Oldest part)
        # We render [:ptr] at X=len(ptr:) (Newer part)

        ptr = self.module.spectrogram_ptr
        buffer = self.module.spectrogram_buffer

        # Part 1: Oldest data (buffer[ptr:])
        part1 = buffer[ptr:]
        self.img_old.setImage(part1, autoLevels=False)
        self.img_old.setPos(0, 0)

        # Part 2: Newer data (buffer[:ptr])
        part2 = buffer[:ptr]
        self.img_new.setImage(part2, autoLevels=False)
        self.img_new.setPos(len(part1), 0)

        # Set Scale
        # X axis: Time (0 to History)
        # Y axis: Frequency (0 to Nyquist)
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2

        # Scale Y to match Frequency
        # Image height is fft_size // 2 + 1
        # We want it to span 0 to Nyquist
        y_scale = nyquist / (buffer.shape[1])

        transform = QTransform().scale(1, y_scale)
        self.img_old.setTransform(transform)
        self.img_new.setTransform(transform)

        self.plot.setLimits(yMin=0, yMax=nyquist)
        self.plot.setYRange(self.module.min_freq, self.module.max_freq)

    def apply_theme(self, theme_name):
        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            # Dark Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_DARK)
        else:
            # Light Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)
