import threading

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer, QRunnable, QThreadPool, QObject, pyqtSignal
from PyQt6.QtGui import QTransform, QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
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
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.core.fft_manager import fft_manager, WARMUP_SIZES
from src.gui.styles import STYLE_TOGGLE_BTN_DARK, STYLE_TOGGLE_BTN_LIGHT


class SpectrogramWorkerSignals(QObject):
    result = pyqtSignal(object)


class SpectrogramWorker(QRunnable):
    def __init__(self, raw_data, window_type, channel_mode):
        super().__init__()
        self.raw_data = raw_data
        self.window_type = window_type
        self.channel_mode = channel_mode
        self.signals = SpectrogramWorkerSignals()

    def run(self):
        # Select Channel
        if self.channel_mode == "Left":
            sig = self.raw_data[:, 0]
        elif self.channel_mode == "Right":
            sig = self.raw_data[:, 1]
        else:
            sig = np.mean(self.raw_data, axis=1)

        # Windowing
        window = get_cached_window(self.window_type, len(sig))
        sig_win = sig * window

        # Window Correction Factor (Coherent Gain)
        win_correction = 1.0 / np.mean(window)

        # FFT
        fft_res = fft_manager.rfft(sig_win)

        # Mag
        mag = np.abs(fft_res)

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

        self.signals.result.emit(mag_db)


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
        self.min_freq = 20
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
            if self.callback_id is not None:
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
                        self.audio_buffer[self.audio_buffer_pos : end_pos] = indata[:, :2]
                    else:
                        self.audio_buffer[self.audio_buffer_pos : end_pos, 0] = indata[:, 0]
                        self.audio_buffer[self.audio_buffer_pos : end_pos, 1] = indata[:, 0]
                else:
                    # Wrap around
                    first_chunk = buffer_len - self.audio_buffer_pos
                    second_chunk = frames - first_chunk

                    if indata.shape[1] >= 2:
                        self.audio_buffer[self.audio_buffer_pos :] = indata[:first_chunk, :2]
                        self.audio_buffer[:second_chunk] = indata[first_chunk:, :2]
                    else:
                        self.audio_buffer[self.audio_buffer_pos :, 0] = indata[:first_chunk, 0]
                        self.audio_buffer[self.audio_buffer_pos :, 1] = indata[:first_chunk, 0]

                        self.audio_buffer[:second_chunk, 0] = indata[first_chunk:, 0]
                        self.audio_buffer[:second_chunk, 1] = indata[first_chunk:, 0]

                self.audio_buffer_pos = (self.audio_buffer_pos + frames) % buffer_len

        outdata.fill(0)


class SpectrogramWidget(QWidget, CompactableWidgetInterface):
    def __init__(self, module: Spectrogram):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        self.module = module
        self.log_spectrogram_buffer = None
        self._last_raw_buffer_id = None
        self.threadpool = QThreadPool()
        self.processing = False
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
        self.controls_group = self._init_controls()
        layout.addWidget(self.controls_group)
        layout.addWidget(self._init_plot())
        self.setLayout(layout)

    def _init_controls(self) -> QGroupBox:
        controls_group = QGroupBox(tr("Settings"))
        # Main layout is horizontal: [Start Button] [Settings Column]
        main_layout = QHBoxLayout()

        # --- Left: Start/Stop Button ---
        self.toggle_btn = QPushButton(tr("Start"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle)
        self.toggle_btn.setFixedWidth(80)
        self.toggle_btn.setSizePolicy(
            self.toggle_btn.sizePolicy().horizontalPolicy(),
            self.toggle_btn.sizePolicy().verticalPolicy(),
        )
        # Make button span height (approximate) or let layout handle it.
        # Ideally, we want it to be tall enough.
        self.toggle_btn.setMinimumHeight(50)

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())
        else:
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)

        main_layout.addWidget(self.toggle_btn)

        # --- Right: Settings Column ---
        # --- Right: Settings Column ---
        settings_layout = QGridLayout()
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setHorizontalSpacing(10)
        settings_layout.setVerticalSpacing(5)

        # Row 1: Channel, FFT Size, Window
        # Channel
        settings_layout.addWidget(QLabel(tr("Channel:")), 0, 0)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["Left", "Right", "Average"])
        self.channel_combo.currentTextChanged.connect(self.on_channel_changed)
        settings_layout.addWidget(self.channel_combo, 0, 1)

        # FFT Size
        settings_layout.addWidget(QLabel(tr("FFT Size:")), 0, 2)
        self.fft_combo = QComboBox()
        self.update_available_fft_sizes(0)  # Initial: Fast
        self.fft_combo.setCurrentText(str(self.module.fft_size))
        self.fft_combo.currentTextChanged.connect(self.on_fft_changed)
        settings_layout.addWidget(self.fft_combo, 0, 3)

        # Window
        settings_layout.addWidget(QLabel(tr("Window:")), 0, 4)
        self.window_combo = QComboBox()
        self.window_combo.addItems(fft_manager.get_available_windows())
        self.window_combo.setCurrentText(self.module.window_type)
        self.window_combo.currentTextChanged.connect(self.on_window_changed)
        settings_layout.addWidget(self.window_combo, 0, 5)

        # Scale (Log/Linear/Mel)
        settings_layout.addWidget(QLabel(tr("Scale:")), 0, 6)
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["Log", "Linear", "Mel"])
        self.scale_combo.currentTextChanged.connect(self.on_scale_changed)
        settings_layout.addWidget(self.scale_combo, 0, 7)

        # Row 2: Colormap, Speed, Frequency Range
        # Colormap
        settings_layout.addWidget(QLabel(tr("Colormap:")), 1, 0)
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(
            [
                "viridis",
                "plasma",
                "inferno",
                "magma",
                "turbo",
                "thermal",
                "flame",
                "yellowy",
                "bipolar",
                "spectrum",
                "cyclic",
            ]
        )
        self.cmap_combo.setCurrentText("turbo")
        self.cmap_combo.currentTextChanged.connect(self.on_cmap_changed)
        settings_layout.addWidget(self.cmap_combo, 1, 1)

        # Sweep Speed
        settings_layout.addWidget(QLabel(tr("Speed:")), 1, 2)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems([tr("Fast (Realtime)"), tr("Medium (1m)"), tr("Slow (5m)"), tr("Meteor (10m)")])
        self.speed_combo.currentIndexChanged.connect(self.on_speed_changed)
        settings_layout.addWidget(self.speed_combo, 1, 3)

        # Frequency Range
        # Min Freq
        settings_layout.addWidget(QLabel(tr("Min Freq:")), 1, 4)
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(0, 96000)
        self.min_freq_spin.setValue(int(self.module.min_freq))
        self.min_freq_spin.setSuffix(" Hz")
        self.min_freq_spin.setFixedWidth(100)
        self.min_freq_spin.valueChanged.connect(self.on_freq_range_changed)
        settings_layout.addWidget(self.min_freq_spin, 1, 5)

        # Max Freq
        settings_layout.addWidget(QLabel(tr("Max Freq:")), 1, 6)
        self.max_freq_spin = QSpinBox()
        self.max_freq_spin.setRange(0, 96000)
        self.max_freq_spin.setValue(int(self.module.max_freq))
        self.max_freq_spin.setSuffix(" Hz")
        self.max_freq_spin.setFixedWidth(100)
        self.max_freq_spin.valueChanged.connect(self.on_freq_range_changed)
        settings_layout.addWidget(self.max_freq_spin, 1, 7)

        # Add stretch to compact the layout to the left
        settings_layout.setColumnStretch(8, 1)

        main_layout.addLayout(settings_layout)
        controls_group.setLayout(main_layout)
        return controls_group

    def _init_plot(self) -> pg.GraphicsLayoutWidget:
        # We use a GraphicsLayoutWidget to hold the Plot and Histogram
        self.win = pg.GraphicsLayoutWidget()

        # Plot Item
        self.plot = self.win.addPlot(title=tr("Spectrogram"))
        self.plot.setLabel("left", tr("Frequency"), units="Hz")
        self.plot.setLabel("bottom", tr("Time"), units="frames")
        self.plot.setLogMode(False, True)  # Default: Log Y-axis

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
        self.hist.sigLookupTableChanged.connect(
            lambda: self.img_new.setLookupTable(self.hist.gradient.getLookupTable(512))
        )

        # Set default colormap
        self.hist.gradient.loadPreset("turbo")
        self.hist.setLevels(-120, 0)  # Default dB range

        return self.win

    def update_available_fft_sizes(self, speed_index):
        current_text = self.fft_combo.currentText()
        self.fft_combo.blockSignals(True)
        self.fft_combo.clear()

        # Fast (Realtime) -> Limit to 8192
        # Others -> Use WARMUP_SIZES (up to 65536)
        if speed_index == 0:
            sizes = [str(s) for s in WARMUP_SIZES if s <= 8192]
        else:
            sizes = [str(s) for s in WARMUP_SIZES]

        self.fft_combo.addItems(sizes)

        # Restore selection if possible
        index = self.fft_combo.findText(current_text)
        if index >= 0:
            self.fft_combo.setCurrentIndex(index)
        else:
            # If current selection is invalid (e.g. was 16384 and switched to Fast), select max available or default
            # Try to select 2048 as default, or last item
            def_idx = self.fft_combo.findText("2048")
            if def_idx >= 0:
                self.fft_combo.setCurrentIndex(def_idx)
            else:
                self.fft_combo.setCurrentIndex(self.fft_combo.count() - 1)

            # Explicitly trigger change since we changed value
            if self.fft_combo.currentText() != current_text:
                self.on_fft_changed(self.fft_combo.currentText())

        self.fft_combo.blockSignals(False)

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
        self.update_available_fft_sizes(idx)
        self.module.sweep_speed_index = idx
        # Reset accumulator on speed change to avoid mixing
        self.module.accumulator = None
        self.module.acc_count = 0

    def on_freq_range_changed(self):
        # Safe check for init
        if not hasattr(self, "min_freq_spin") or not hasattr(self, "max_freq_spin"):
            return

        self.module.min_freq = self.min_freq_spin.value()
        self.module.max_freq = self.max_freq_spin.value()

        min_f = float(self.module.min_freq)
        max_f = float(self.module.max_freq)

        scale_type = self.scale_combo.currentText()

        if scale_type == "Log":
            # Avoid log(0) or negative
            if min_f <= 0:
                min_f = 1.0  # 1Hz minimum for log scale
            if max_f <= min_f:
                max_f = min_f + 10.0  # Valid range

            self.plot.setYRange(np.log10(min_f), np.log10(max_f))
        elif scale_type == "Mel":
            if max_f <= min_f:
                max_f = min_f + 10.0
            mel_min = 2595.0 * np.log10(1.0 + min_f / 700.0)
            mel_max = 2595.0 * np.log10(1.0 + max_f / 700.0)
            self.plot.setYRange(mel_min, mel_max)
        else:
            self.plot.setYRange(min_f, max_f)

    def on_scale_changed(self, val):
        is_log = val == "Log"
        is_mel = val == "Mel"
        self.plot.setLogMode(False, is_log)

        if is_mel:
            self.plot.setLabel("left", tr("Frequency"), units="Mel")
        else:
            self.plot.setLabel("left", tr("Frequency"), units="Hz")

        self.on_freq_range_changed()  # Re-apply limits safely

    def update_spectrogram(self):
        if not self.module.is_running or self.processing:
            return

        # Get latest data from buffer
        # We take the last fft_size samples
        # Copy to ensure thread safety when passed to worker
        raw_data = self.module.get_latest_samples(self.module.fft_size).copy()

        self.processing = True
        worker = SpectrogramWorker(raw_data, self.module.window_type, self.module.channel_mode)
        worker.signals.result.connect(self.on_worker_result)
        self.threadpool.start(worker)

    def on_worker_result(self, mag_db):
        self.processing = False
        if not self.module.is_running:
            return

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

        # Check Scale Mode
        scale_mode = self.scale_combo.currentText()

        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2

        # Prepare Display Data
        if scale_mode in ("Log", "Mel"):
            # Resample to Log or Mel Scale
            # Cache the map
            # We map from Linear Bins (0..N/2) to Log/Mel Bins (0..N/2)

            if scale_mode == "Log":
                min_f = max(1, self.module.min_freq)
                max_f = max(min_f + 1, self.module.max_freq)  # Ensure max > min
            else:
                min_f = max(0, self.module.min_freq)
                max_f = max(min_f + 1, self.module.max_freq)

            # Key for cache: (fft_size, min_f, max_f, scale_mode)
            cache_key = (self.module.fft_size, min_f, max_f, scale_mode)
            map_changed = False
            if not hasattr(self, "_log_map_cache") or self._log_map_cache[0] != cache_key:
                # Generate Map
                n_bins = buffer.shape[1]

                if scale_mode == "Log":
                    # Log spaced frequencies
                    target_freqs = np.logspace(np.log10(min_f), np.log10(max_f), n_bins)
                else:
                    # Mel spaced frequencies
                    mel_min = 2595.0 * np.log10(1.0 + min_f / 700.0)
                    mel_max = 2595.0 * np.log10(1.0 + max_f / 700.0)
                    mel_freqs = np.linspace(mel_min, mel_max, n_bins)
                    target_freqs = 700.0 * (10.0 ** (mel_freqs / 2595.0) - 1.0)

                # Convert to linear bin indices
                freq_res = sample_rate / self.module.fft_size
                linear_indices = target_freqs / freq_res
                # Clamp
                linear_indices = np.clip(linear_indices, 0, n_bins - 1).astype(int)
                self._log_map_cache = (cache_key, linear_indices)
                map_changed = True

            indices = self._log_map_cache[1]

            # Optimized Incremental Update
            # Check if raw buffer was reset or resized
            raw_id = id(buffer)
            if self._last_raw_buffer_id != raw_id:
                map_changed = True
                self._last_raw_buffer_id = raw_id

            if map_changed or self.log_spectrogram_buffer is None:
                # Full update needed (Parameter change or reset)
                self.log_spectrogram_buffer = buffer[:, indices].copy()
            else:
                # Incremental update: Update only the latest row
                # The latest row was written at (ptr - 1)
                idx = (ptr - 1 + self.module.history_length) % self.module.history_length
                self.log_spectrogram_buffer[idx] = final_mag_db[indices]

            display_buffer = self.log_spectrogram_buffer

            # Transform for Target Mode
            if scale_mode == "Log":
                y_min = np.log10(min_f)
                y_max = np.log10(max_f)
            else:
                y_min = 2595.0 * np.log10(1.0 + min_f / 700.0)
                y_max = 2595.0 * np.log10(1.0 + max_f / 700.0)

            y_scale = (y_max - y_min) / display_buffer.shape[1]

            transform = QTransform().translate(0, y_min).scale(1, y_scale)

            # Limits in Target Domain
            self.plot.setLimits(yMin=y_min, yMax=y_max)
            self.plot.setYRange(y_min, y_max)

        else:
            # Linear Scale
            display_buffer = buffer
            self.log_spectrogram_buffer = None  # Free memory when not used

            # Transform for Linear Mode
            # Image Y: 0..Height -> 0..Nyquist
            y_scale = nyquist / (buffer.shape[1])
            transform = QTransform().scale(1, y_scale)

            self.plot.setLimits(yMin=0, yMax=nyquist)
            self.plot.setYRange(self.module.min_freq, self.module.max_freq)

        # Part 1: Oldest data (buffer[ptr:])
        part1 = display_buffer[ptr:]
        self.img_old.setImage(part1, autoLevels=False)
        self.img_old.setPos(0, 0)
        self.img_old.setTransform(transform)

        # Part 2: Newer data (buffer[:ptr])
        part2 = display_buffer[:ptr]
        self.img_new.setImage(part2, autoLevels=False)
        self.img_new.setPos(len(part1), 0)
        self.img_new.setTransform(transform)

    def apply_theme(self, theme_name):
        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            # Dark Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_DARK)
        else:
            # Light Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        if hasattr(self, "controls_group"):
            self.controls_group.setHidden(compact)
        if hasattr(self, "hist"):
            self.hist.setVisible(not compact)
