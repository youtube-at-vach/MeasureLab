import logging
import queue
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class BitDepthAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 4096
        self.write_head = 0
        self.audio_queue = queue.Queue()

        # Configs
        self.integration_time = 0.5  # Seconds to integrate before updating display
        self.history_length = 100  # Number of history points for ENOB graph

        # State - Calculation
        self._samples_buffer = []  # Accumulate samples for integration
        self._last_update_time = 0
        self._current_bit_depth = 0.0
        self._current_delta_hist = None
        self._current_bit_distribution = None
        self._bit_depth_history = deque(maxlen=self.history_length)

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Bit Depth Analyzer"

    @property
    def description(self) -> str:
        return "Analyzes effective bit depth and quantization noise."

    def get_widget(self):
        return BitDepthAnalyzerWidget(self)

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self._samples_buffer = []
        self._current_bit_depth = 0.0
        self._bit_depth_history.clear()
        self._last_update_time = time.time()

        # Clear queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        def callback(indata, outdata, frames, time_info, status):
            if status:
                logger.debug(status)

            # Use channel 0 (Left) for now for single channel analysis
            # Or mix down to mono? Let's take Left for now.
            if indata.shape[1] >= 1:
                self.audio_queue.put(indata[:, 0].copy())

            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def process_queue(self):
        # Fetch all available data
        while not self.audio_queue.empty():
            try:
                data = self.audio_queue.get_nowait()
                self._samples_buffer.append(data)
            except queue.Empty:
                break

        current_time = time.time()
        if current_time - self._last_update_time >= self.integration_time:
            self._analyze_buffer()
            self._last_update_time = current_time

    def _analyze_buffer(self):
        if not self._samples_buffer:
            return

        # Concatenate all chunks
        full_data = np.concatenate(self._samples_buffer)
        self._samples_buffer = []  # Clear buffer after processing

        if len(full_data) < 2:
            return

        # 1. Delta Estimation & Bit Depth
        # Sort unique absolute values to find smallest difference
        # However, finding ALL unique differences is O(N^2) or O(N log N) which is heavy.
        # Approximation: Difference between adjacent samples.
        diffs = np.abs(np.diff(full_data))

        # Filter out exact zeros (digital silence or repeated samples)
        nonzero_diffs = diffs[diffs > 1e-12]

        if len(nonzero_diffs) > 0:
            # Find the smallest non-zero step
            # Robustness: take the 1st percentile to ignore potential glitches/outliers closer to 0?
            # Or just min? Min is theoretically correct for quantization step.
            min_delta = np.min(nonzero_diffs)

            # Estimate bit depth
            # Full Scale assumed 1.0 (actually -1.0 to 1.0 -> range 2.0)
            # Step size q = 2 * FullScale / 2^B
            # If normalized to +/- 1.0, Range = 2.0.
            # q = 2.0 / 2^B  => 2^B = 2.0 / q => B = log2(2.0/q)
            # B = 1 - log2(q)

            if min_delta > 0:
                estimated_bits = 1 - np.log2(min_delta)
                # Clamp reasonably (e.g. 0 to 64)
                estimated_bits = max(0, min(64, estimated_bits))
            else:
                 estimated_bits = 0 # Should not happen due to filter
        else:
             estimated_bits = 0 # Digital silence

        self._current_bit_depth = estimated_bits
        self._bit_depth_history.append(estimated_bits)

        # 2. Delta Histogram
        # Log10 of differences
        if len(nonzero_diffs) > 0:
            log_diffs = np.log10(nonzero_diffs)
            hist, bin_edges = np.histogram(log_diffs, bins=50, range=(-9, 0)) # 1e-9 to 1.0
            self._current_delta_hist = (hist, bin_edges)

        # 3. LSB / Bit Activity
        # Convert to 32-bit int representation
        # Scale to full 32-bit range
        # Note: 32-bit float has 24 bits significand. 
        # But if source is 16-bit int -> float, scaling up checks which bits are active.

        # Int32 conversion: data * 2**31
        # We need to handle clipping
        clipped_data = np.clip(full_data, -1.0, 1.0)
        int_data = (clipped_data * (2**31 - 1)).astype(np.int32)
        uint_data = int_data.view(np.uint32)

        # Check active bits
        # We want to know probability of each bit being 1 (or changing?)
        # "Activity" usually means the bit Toggles.
        # But simply checking if the bit is ever 1 in the block is a good "Active" check if signal is zero-mean.
        # Better: Calculate probability of bit being 1. For random noise (dither), likely 0.5.
        # For truncated bits, 0.0.

        # We need a fast way to count bits.
        # iterate 0 to 31
        bit_counts = np.zeros(32)
        n_samples = len(uint_data)

        # Use bitwise operations on the whole array
        for i in range(32):
            mask = np.uint32(1 << i)
            # count how many samples have this bit set
            count = np.count_nonzero(uint_data & mask)
            bit_counts[i] = count / n_samples

        self._current_bit_distribution = bit_counts


class BitDepthAnalyzerWidget(QWidget):
    def __init__(self, module: BitDepthAnalyzer):
        super().__init__()
        self.module = module

        # Heatmap storage (Time x Bits)
        self.heatmap_history_len = 50
        self.heatmap_data = np.zeros((self.heatmap_history_len, 32))

        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui)
        self.timer.setInterval(100) # 10fps UI update

    def init_ui(self):
        layout = QVBoxLayout()

        # Controls
        controls_group = QGroupBox(tr("Controls"))
        h_layout = QHBoxLayout()

        self.toggle_btn = QPushButton(tr("Start Analysis"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle)
        self.toggle_btn.setStyleSheet(
            "QPushButton { background-color: #ccffcc; color: black; } QPushButton:checked { background-color: #ffcccc; color: black; }"
        )
        h_layout.addWidget(self.toggle_btn)

        self.reset_btn = QPushButton(tr("Reset"))
        self.reset_btn.clicked.connect(self.on_reset)
        h_layout.addWidget(self.reset_btn)

        h_layout.addStretch()
        controls_group.setLayout(h_layout)
        layout.addWidget(controls_group)

        # Dashboard Layout
        # Top: ENOB History & Bit Depth Number
        # Bottom: Heatmap & Histogram

        # --- Top Section ---
        top_layout = QHBoxLayout()

        # ENOB Display
        self.enob_value_label = QLabel("0.0 bits")
        self.enob_value_label.setStyleSheet("font-size: 48px; font-weight: bold; color: #00ff00;")
        try:
            from PyQt6.QtCore import Qt
            self.enob_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except (TypeError, AttributeError):
            # Fallback for mocked environments in tests
            pass

        top_layout.addWidget(self.enob_value_label)

        # ENOB Plot
        self.enob_plot = pg.PlotWidget(title=tr("Effective Bit Depth History"))
        self.enob_plot.setLabel('left', 'Bits')
        self.enob_plot.setYRange(0, 32)
        self.enob_plot.showGrid(y=True)
        self.enob_curve = self.enob_plot.plot(pen='y')
        top_layout.addWidget(self.enob_plot)
        top_layout.setStretch(0, 1)
        top_layout.setStretch(1, 2)

        layout.addLayout(top_layout, stretch=1)

        # --- Bottom Section ---
        bottom_layout = QHBoxLayout()

        # Heatmap
        # PlotItem for heat map
        self.heatmap_plot = pg.PlotWidget(title=tr("Bit Activity (LSB to MSB)"))
        self.heatmap_plot.setLabel('left', tr("Log Time"))
        self.heatmap_plot.setLabel('bottom', tr("Bit Index (0=LSB)"))
        self.heatmap_plot.setXRange(-0.5, 31.5)
        self.heatmap_plot.setYRange(0, self.heatmap_history_len)

        # ImageItem
        self.heatmap_img = pg.ImageItem()
        self.heatmap_plot.addItem(self.heatmap_img)

        # Colormap (Black -> Blue -> Red -> Yellow)
        # 0.0 (Inactive) -> 0.5 (Random/Active) -> 1.0 (Stuck High?)
        pos = np.array([0.0, 0.5, 1.0])
        color = np.array([
            [0, 0, 0, 255], 
            [0, 255, 0, 255], 
            [255, 255, 0, 255]
        ], dtype=np.ubyte)
        map = pg.ColorMap(pos, color)
        self.heatmap_img.setLookupTable(map.getLookupTable(0.0, 1.0))

        bottom_layout.addWidget(self.heatmap_plot, stretch=2)

        # Delta Histogram
        self.hist_plot = pg.PlotWidget(title=tr("Quantization Step Distribution"))
        self.hist_plot.setLabel('bottom', 'Log10(Delta)')
        self.hist_plot.setLabel('left', 'Count')
        self.hist_bar = pg.BarGraphItem(x=[], height=[], width=0.1, brush='b')
        self.hist_plot.addItem(self.hist_bar)

        bottom_layout.addWidget(self.hist_plot, stretch=1)

        layout.addLayout(bottom_layout, stretch=2)

        self.setLayout(layout)

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop Analysis"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start Analysis"))

    def on_reset(self):
        self.heatmap_data.fill(0)
        self.heatmap_img.setImage(self.heatmap_data, autoLevels=False, levels=(0.0, 1.0))
        self.module._bit_depth_history.clear()
        self.enob_curve.setData([], [])
        self.enob_value_label.setText("-- bits")

    def update_ui(self):
        self.module.process_queue()

        # Update ENOB Label
        bits = self.module._current_bit_depth
        self.enob_value_label.setText(f"{bits:.1f} bits")

        # Update ENOB History
        if self.module._bit_depth_history:
            self.enob_curve.setData(list(self.module._bit_depth_history))

        # Update Heatmap
        if self.module._current_bit_distribution is not None:
            # Shift history
            self.heatmap_data = np.roll(self.heatmap_data, 1, axis=0)
            self.heatmap_data[0] = self.module._current_bit_distribution
        self.heatmap_img.setImage(self.heatmap_data, autoLevels=False, levels=(0.0, 1.0))

        # Update Histogram
        if self.module._current_delta_hist:
            hist, edges = self.module._current_delta_hist
            # x is centers of bins
            x = (edges[:-1] + edges[1:]) / 2
            self.hist_bar.setOpts(x=x, height=hist, width=(x[1]-x[0]))
