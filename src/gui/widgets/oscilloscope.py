import logging

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.ring_buffer import RingBuffer
from src.core.localization import tr
from src.core.utils import format_si
from src.measurement_modules.base import MeasurementModule
from typing import List
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.core.comparison_manager import ComparisonTrace, AxisMetadata, CalibrationInfo
from src.gui.styles import (
    STYLE_TOGGLE_BTN_DARK,
    STYLE_TOGGLE_BTN_LIGHT,
    STYLE_LABEL_LEFT_CH_DARK,
    STYLE_LABEL_RIGHT_CH_DARK,
    STYLE_LABEL_CURSOR_DARK,
    STYLE_LABEL_LEFT_CH_LIGHT,
    STYLE_LABEL_RIGHT_CH_LIGHT,
    STYLE_LABEL_CURSOR_LIGHT,
)


logger = logging.getLogger(__name__)


class Oscilloscope(MeasurementModule):
    MIN_BUFFER_SIZE = 8192
    MAX_DISPLAY_SAMPLES = 8192
    TRIGGER_SEARCH_WINDOW_SIZE = 2048
    TRIGGER_SEARCH_FRACTION = 0.25
    MAX_TRIGGER_SEARCH_WINDOW_SIZE = 8192

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        # Settings
        self.timebase = 0.01  # Seconds per division (approx) -> Total view window
        # Buffer enough for low frequency analysis, but we'll display a subset
        self.buffer_size = self._recommended_buffer_size(self.timebase)
        # Double the buffer size to avoid wrap-around concatenation
        self.input_data = np.zeros((self.buffer_size * 2, 2))
        self.write_index = 0

        self.gain = 1.0
        self.trigger_source = 0  # 0: Left, 1: Right
        self.trigger_mode = "Auto"  # 'Auto', 'Normal', 'Single'
        self.trigger_slope = "Rising"  # 'Rising', 'Falling'
        self.trigger_level = 0.0
        self.show_left = True
        self.show_right = True

        # Per-channel vertical display scale (multiplier)
        self.vscale_left = 1.0
        self.vscale_right = 1.0

        # Single-shot trigger state
        self.single_shot_armed = False
        self.single_shot_fired = False

        # Math Mode
        self.math_mode = "Off"  # 'Off', 'Derivative', 'Integral'

        # Filter Settings
        self.filter_type = "None"  # 'None', 'LPF', 'HPF', 'BPF'
        self.filter_cutoff = 1000.0  # For LPF/HPF
        self.filter_low = 1000.0  # For BPF
        self.filter_high = 2000.0  # For BPF

        # Persistence Settings
        self.persistence_mode = False
        self.persistence_decay = 0.90
        self.persistence_intensity = 0.5
        # Buffers for persistence (initially None, created on demand)
        self.heatmap_l = None
        self.heatmap_r = None
        self.heatmap_size = (600, 400)  # Width, Height (pixels/bins)

        # High-performance transfer buffer (Ring Buffer)
        # Replaces queue to avoid allocation in audio callback
        self.transfer_buffer_size = 65536
        self.transfer_buffer = RingBuffer(self.transfer_buffer_size, 2, dtype=np.float32)

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Oscilloscope"

    @property
    def description(self) -> str:
        return "Time-domain waveform monitor."

    @staticmethod
    def _accumulate_heatmap(t, y, heatmap, bins, rng, intensity):
        """Optimized histogram accumulation for persistence display."""
        w, h = bins
        x_min, x_max = rng[0]
        y_min, y_max = rng[1]

        if x_max <= x_min or y_max <= y_min:
            return

        # Pre-compute scales
        x_scale = w / (x_max - x_min)
        y_scale = h / (y_max - y_min)

        # Filter valid Y data
        mask = (y >= y_min) & (y <= y_max)
        if not np.any(mask):
            return

        y_valid = y[mask]
        t_valid = t[mask]

        # Map to indices
        x_idx = ((t_valid - x_min) * x_scale).astype(np.int32)
        y_idx = ((y_valid - y_min) * y_scale).astype(np.int32)

        # Handle edge cases (values exactly at max map to index N, should be N-1)
        x_idx[x_idx == w] = w - 1
        y_idx[y_idx == h] = h - 1

        # Clamp for safety
        np.clip(x_idx, 0, w - 1, out=x_idx)
        np.clip(y_idx, 0, h - 1, out=y_idx)

        # Accumulate
        np.add.at(heatmap, (x_idx, y_idx), intensity * 100)

    def get_widget(self):
        return OscilloscopeWidget(self)

    def reset_persistence(self):
        w, h = self.heatmap_size
        self.heatmap_l = np.zeros((w, h))
        self.heatmap_r = np.zeros((w, h))

    def _recommended_trigger_search_window(self, required_samples):
        adaptive_window = int(required_samples * self.TRIGGER_SEARCH_FRACTION)
        return min(
            max(self.TRIGGER_SEARCH_WINDOW_SIZE, adaptive_window),
            self.MAX_TRIGGER_SEARCH_WINDOW_SIZE,
        )

    def _sample_rate_hz(self):
        try:
            sample_rate = int(getattr(self.audio_engine, "sample_rate", 48000))
        except (TypeError, ValueError):
            sample_rate = 48000
        return max(1, sample_rate)

    def _recommended_buffer_size(self, window_duration):
        sample_rate = self._sample_rate_hz()
        required_samples = max(1, int(window_duration * sample_rate))
        search_window = self._recommended_trigger_search_window(required_samples)
        return max(self.MIN_BUFFER_SIZE, required_samples + search_window)

    def _ensure_buffer_capacity(self, window_duration):
        sample_rate = self._sample_rate_hz()
        required_samples = max(1, int(window_duration * sample_rate))
        if self.buffer_size < self.MIN_BUFFER_SIZE and required_samples <= self.buffer_size:
            return

        required_size = self._recommended_buffer_size(window_duration)
        if required_size <= self.buffer_size:
            return

        old_buffer_size = self.buffer_size
        old_data = self.input_data
        old_write_index = self.write_index

        # Reallocate only on the UI thread. Keep the ring-buffer invariant that
        # write_index is the logical origin (oldest sample) for _get_data_slice().
        self.buffer_size = required_size
        self.input_data = np.zeros((self.buffer_size * 2, 2), dtype=old_data.dtype)
        old_available = min(old_buffer_size, self.buffer_size)
        old_start = (old_write_index - old_available) % old_buffer_size
        new_start = self.buffer_size - old_available
        if old_start + old_available <= old_buffer_size:
            self.input_data[new_start : new_start + old_available] = old_data[old_start : old_start + old_available]
        else:
            split = old_buffer_size - old_start
            self.input_data[new_start : new_start + split] = old_data[old_start:old_buffer_size]
            self.input_data[new_start + split : new_start + old_available] = old_data[: old_available - split]

        self.input_data[self.buffer_size :] = self.input_data[: self.buffer_size]
        self.write_index = 0

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self._ensure_buffer_capacity(self.timebase)
        self.input_data = np.zeros((self.buffer_size * 2, 2))
        self.write_index = 0

        # Reset transfer buffer
        self.transfer_buffer.reset()

        # Reset heatmaps
        if self.persistence_mode:
            self.reset_persistence()

        if self.trigger_mode == "Single":
            self.single_shot_armed = True
            self.single_shot_fired = False

        def callback(indata, outdata, frames, time, status):
            if status:
                logger.debug(status)

            # Write to transfer buffer (RingBuffer handles lock and wrapping)
            self.transfer_buffer.write(indata)

            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def process_queue(self):
        # Poll transfer buffer
        new_data = self.transfer_buffer.read()
        n_frames = len(new_data)
        if n_frames == 0:
            return

        # Now process new_data into input_data (display buffer)
        if n_frames > self.buffer_size:
            # Just take the last part
            last_part = new_data[-self.buffer_size :]
            self.input_data[: self.buffer_size] = last_part
            self.input_data[self.buffer_size :] = last_part
            self.write_index = 0
        else:
            # Wrapped write
            idx = self.write_index
            end_idx = idx + n_frames
            if end_idx <= self.buffer_size:
                self.input_data[idx:end_idx] = new_data
                self.input_data[idx + self.buffer_size : end_idx + self.buffer_size] = new_data
            else:
                # Split
                part1_len = self.buffer_size - idx

                # Write to end of primary buffer and start of mirror buffer
                self.input_data[idx : self.buffer_size] = new_data[:part1_len]
                self.input_data[idx + self.buffer_size :] = new_data[:part1_len]

                # Write to start of primary buffer and start of mirror buffer
                part2_len = n_frames - part1_len
                self.input_data[:part2_len] = new_data[part1_len:]
                self.input_data[self.buffer_size : self.buffer_size + part2_len] = new_data[part1_len:]

            self.write_index = (idx + n_frames) % self.buffer_size

    def get_measurements(self, data):
        """
        Calculate measurements (RMS, Vpp) for the given data, applying calibration.
        Returns a dict with 'l_rms', 'l_vpp', 'r_rms', 'r_vpp'.
        """
        if data is None or len(data) == 0:
            return {"l_rms": 0.0, "l_vpp": 0.0, "r_rms": 0.0, "r_vpp": 0.0}

        # Apply Input Sensitivity (Calibration)
        # raw data is -1.0 to 1.0 (FS).
        # sensitivity is Volts per FS (Peak).
        sensitivity = self.audio_engine.calibration.input_sensitivity

        l_data = data[:, 0]
        r_data = data[:, 1]

        # RMS calculation
        # RMS(Volts) = RMS(FS) * Sensitivity
        l_rms = np.sqrt(np.mean(l_data**2)) * sensitivity
        r_rms = np.sqrt(np.mean(r_data**2)) * sensitivity

        # Vpp calculation
        # Vpp(Volts) = (Max(FS) - Min(FS)) * Sensitivity
        l_vpp = (np.max(l_data) - np.min(l_data)) * sensitivity
        r_vpp = (np.max(r_data) - np.min(r_data)) * sensitivity

        return {"l_rms": l_rms, "l_vpp": l_vpp, "r_rms": r_rms, "r_vpp": r_vpp}

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def _get_data_slice(self, start_offset, length):
        """Returns a contiguous array of length samples starting at logical offset start_offset (0 = oldest)."""
        if length <= 0:
            return np.empty((0, 2))

        idx = (self.write_index + start_offset) % self.buffer_size
        end_idx = idx + length

        return self.input_data[idx:end_idx].copy()

    def get_display_data(self, window_duration):
        """
        Get triggered data for display.
        window_duration: float, seconds of data to display
        """
        self._ensure_buffer_capacity(window_duration)
        sample_rate = self._sample_rate_hz()
        required_samples = int(window_duration * sample_rate)

        if required_samples > self.buffer_size:
            required_samples = self.buffer_size

        if self.trigger_mode == "Single" and not self.single_shot_armed:
            return None

        # Simple Trigger Search
        # Look for crossing of trigger_level with correct slope
        # We search in the range [0, buffer_size - required_samples] to ensure we have enough data after trigger

        search_end = self.buffer_size - required_samples
        if search_end <= 0:
            # Buffer too small for requested window, just return what we have (the last required_samples)
            start_offset = max(0, self.buffer_size - required_samples)
            return self._get_data_slice(start_offset, required_samples)

        # Limit search to recent history to be responsive (e.g. last 50% of possible range)
        # But we need enough pre-trigger data?
        # Usually oscilloscope shows trigger point at center or left. Let's put it at the left for now.

        # We search backwards from the end-required_samples to find the most recent trigger event
        # Or search forwards?
        # Let's search in the last 'search_window' samples
        search_window = self._recommended_trigger_search_window(required_samples)  # Limit search to avoid high CPU
        start_idx = max(0, search_end - search_window)

        # Extract only the search window subset
        search_length = search_end - start_idx
        subset_data = self._get_data_slice(start_idx, search_length)
        subset = subset_data[:, self.trigger_source]

        # Find crossings
        # Rising: previous < level <= current
        # Falling: previous > level >= current

        if self.trigger_slope == "Rising":
            crossings = np.where((subset[:-1] < self.trigger_level) & (subset[1:] >= self.trigger_level))[0]
        else:
            crossings = np.where((subset[:-1] > self.trigger_level) & (subset[1:] <= self.trigger_level))[0]

        if len(crossings) > 0:
            # Pick the last one for most recent update
            trigger_offset_in_subset = crossings[-1] + 1  # +1 because crossing is between i and i+1
            trigger_idx = start_idx + trigger_offset_in_subset

            if self.trigger_mode == "Single":
                self.single_shot_fired = True
                self.single_shot_armed = False

            return self._get_data_slice(trigger_idx, required_samples)
        else:
            # No trigger found
            if self.trigger_mode == "Auto":
                # Return latest data
                # Corresponds to last required_samples
                start_offset = self.buffer_size - required_samples
                return self._get_data_slice(start_offset, required_samples)
            else:
                # Normal mode: return None (keep last frame)
                return None

    @staticmethod
    def _interp_crossing_time(t: np.ndarray, y: np.ndarray, level: float, direction: str):
        """Return interpolated crossing time for the first crossing in the requested direction.

        direction: 'rising' or 'falling'
        """
        if t is None or y is None or len(t) < 2:
            return None
        if direction == "rising":
            mask = (y[:-1] < level) & (y[1:] >= level)
        else:
            mask = (y[:-1] > level) & (y[1:] <= level)

        idx = np.argmax(mask)
        if not mask[idx]:
            return None
        i = int(idx)
        y0 = float(y[i])
        y1 = float(y[i + 1])
        t0 = float(t[i])
        t1 = float(t[i + 1])
        denom = y1 - y0
        if denom == 0:
            return t0
        frac = (level - y0) / denom
        if frac < 0:
            frac = 0
        elif frac > 1:
            frac = 1
        return t0 + frac * (t1 - t0)

    @staticmethod
    def estimate_frequency_hz(t: np.ndarray, y: np.ndarray):
        """Estimate frequency from rising zero-crossings (DC-removed)."""
        if t is None or y is None or len(t) < 4:
            return None
        yy = np.asarray(y, dtype=float)
        tt = np.asarray(t, dtype=float)
        if yy.size != tt.size:
            return None

        yy = yy - np.mean(yy)
        crossings = np.where((yy[:-1] < 0.0) & (yy[1:] >= 0.0))[0]
        if len(crossings) < 2:
            return None

        # Vectorized interpolation
        # Since crossings are defined as y[i] < 0 and y[i+1] >= 0,
        # denom = y[i+1] - y[i] is strictly positive.
        idx = crossings
        y0 = yy[idx]
        y1 = yy[idx + 1]
        t0 = tt[idx]
        t1 = tt[idx + 1]

        denom = y1 - y0
        frac = -y0 / denom
        times = t0 + frac * (t1 - t0)

        if len(times) < 2:
            return None

        periods = np.diff(np.asarray(times, dtype=float))
        periods = periods[np.isfinite(periods) & (periods > 0)]
        if periods.size == 0:
            return None

        period = float(np.median(periods))
        if period <= 0:
            return None
        return 1.0 / period

    @staticmethod
    def estimate_rise_fall_times_s(t: np.ndarray, y: np.ndarray):
        """Estimate 10-90% rise time and 90-10% fall time for step-like waveforms.

        This implementation measures *within a single edge neighborhood* to avoid accidentally
        spanning multiple periods (a common failure mode on square waves).

        Returns (rise_time_s, fall_time_s, low_level, high_level) where times can be None.
        """
        if t is None or y is None or len(t) < 4:
            return (None, None, None, None)

        yy = np.asarray(y, dtype=float)
        tt = np.asarray(t, dtype=float)
        if yy.size != tt.size:
            return (None, None, None, None)

        # Robust low/high estimates from quantiles.
        low_q = float(np.percentile(yy, 10))
        high_q = float(np.percentile(yy, 90))
        if not np.isfinite(low_q) or not np.isfinite(high_q):
            return (None, None, None, None)

        low_level = min(low_q, high_q)
        high_level = max(low_q, high_q)
        amp = high_level - low_level
        if amp <= 1e-9:
            return (None, None, low_level, high_level)

        # Heuristic: only attempt rise/fall when waveform looks step-like.
        near_low = np.mean(yy <= (low_level + 0.2 * amp))
        near_high = np.mean(yy >= (high_level - 0.2 * amp))
        if not (near_low > 0.05 and near_high > 0.05):
            return (None, None, low_level, high_level)

        th10 = low_level + 0.1 * amp
        th90 = low_level + 0.9 * amp
        th50 = low_level + 0.5 * amp

        def _interp_time_at(i_local: int, level: float):
            y0 = float(yy[i_local])
            y1 = float(yy[i_local + 1])
            t0 = float(tt[i_local])
            t1 = float(tt[i_local + 1])
            denom = y1 - y0
            if denom == 0:
                return t0
            frac = (level - y0) / denom
            if frac < 0.0:
                frac = 0.0
            elif frac > 1.0:
                frac = 1.0
            return t0 + frac * (t1 - t0)

        n = len(yy)
        win = min(max(16, n // 8), 4000)
        center = n // 2

        def _pick_edge(direction: str):
            if direction == "rising":
                candidates = np.where((yy[:-1] < th50) & (yy[1:] >= th50))[0]
            else:
                candidates = np.where((yy[:-1] > th50) & (yy[1:] <= th50))[0]
            if candidates.size == 0:
                return None
            dy = np.abs(yy[candidates + 1] - yy[candidates])
            dist = np.abs(candidates - center)
            dist_w = 1.0 - (dist / max(1, center))
            score = dy * (0.25 + 0.75 * dist_w)
            return int(candidates[int(np.argmax(score))])

        def _rise_time_from_edge(i50: int):
            lo = max(0, i50 - win)
            hi = min(n - 2, i50 + win)
            pre = np.where((yy[lo:hi] < th10) & (yy[lo + 1 : hi + 1] >= th10))[0]
            if pre.size == 0:
                return None
            i10 = lo + int(pre[-1])
            post = np.where((yy[i10:hi] < th90) & (yy[i10 + 1 : hi + 1] >= th90))[0]
            if post.size == 0:
                return None
            i90 = i10 + int(post[0])
            t10 = _interp_time_at(i10, th10)
            t90 = _interp_time_at(i90, th90)
            dt = float(t90) - float(t10)
            return dt if dt > 0 else None

        def _fall_time_from_edge(i50: int):
            lo = max(0, i50 - win)
            hi = min(n - 2, i50 + win)
            pre = np.where((yy[lo:hi] > th90) & (yy[lo + 1 : hi + 1] <= th90))[0]
            if pre.size == 0:
                return None
            i90 = lo + int(pre[-1])
            post = np.where((yy[i90:hi] > th10) & (yy[i90 + 1 : hi + 1] <= th10))[0]
            if post.size == 0:
                return None
            i10 = i90 + int(post[0])
            t90 = _interp_time_at(i90, th90)
            t10 = _interp_time_at(i10, th10)
            dt = float(t10) - float(t90)
            return dt if dt > 0 else None

        rise_time = None
        i50r = _pick_edge("rising")
        if i50r is not None:
            rise_time = _rise_time_from_edge(i50r)

        fall_time = None
        i50f = _pick_edge("falling")
        if i50f is not None:
            fall_time = _fall_time_from_edge(i50f)

        return (rise_time, fall_time, low_level, high_level)


class OscilloscopeWidget(QWidget, CompactableWidgetInterface, ComparableWidgetInterface):
    # View constants
    VIEW_Y_MIN = -1.1
    VIEW_Y_MAX = 1.1

    def __init__(self, module: Oscilloscope):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        ComparableWidgetInterface.__init__(self)
        self.module = module
        self._rgba_buffer = None
        self._clip_buffer = None
        self.last_display_data = None
        self.last_display_time = None

        # Optimization: Time array cache
        self._time_array_cache = None
        self._time_array_cache_params = (None, None)  # (window_duration, length)

        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.setInterval(30)  # 30ms refresh

    def closeEvent(self, event: QCloseEvent):
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)

    def init_ui(self):
        main_layout = QHBoxLayout()

        # --- Left Panel (Display) ---
        left_layout = self._setup_left_panel()
        main_layout.addLayout(left_layout, stretch=1)  # Give priority to plot

        # --- Right Panel (Controls) ---
        self.right_widget = self._setup_right_panel()

        # Math Curve
        self._setup_math_view()

        main_layout.addWidget(self.right_widget)
        self.setLayout(main_layout)

    def _setup_left_panel(self):
        left_layout = QVBoxLayout()

        # Measurements
        self.meas_group = QGroupBox(tr("Measurements"))
        meas_layout = QVBoxLayout()

        meas_row_1 = QHBoxLayout()
        self.meas_l_label = QLabel(tr("L: Vrms: 0.000 V  Vpp: 0.000 V"))
        self.meas_l_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
        meas_row_1.addWidget(self.meas_l_label)

        self.meas_r_label = QLabel(tr("R: Vrms: 0.000 V  Vpp: 0.000 V"))
        self.meas_r_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
        meas_row_1.addWidget(self.meas_r_label)
        meas_row_1.addStretch()
        meas_layout.addLayout(meas_row_1)

        self.meas_l_auto_label = QLabel(tr("Freq") + ": --  " + tr("Rise") + ": --  " + tr("Fall") + ": --")
        self.meas_l_auto_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
        self.meas_l_auto_label.setVisible(False)
        meas_layout.addWidget(self.meas_l_auto_label)

        self.meas_r_auto_label = QLabel(tr("Freq") + ": --  " + tr("Rise") + ": --  " + tr("Fall") + ": --")
        self.meas_r_auto_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
        self.meas_r_auto_label.setVisible(False)
        meas_layout.addWidget(self.meas_r_auto_label)

        self.meas_group.setLayout(meas_layout)
        left_layout.addWidget(self.meas_group)

        # Cursor Info
        self.cursor_info_label = QLabel(tr("Cursors: Off"))
        self.cursor_info_label.setStyleSheet(STYLE_LABEL_CURSOR_DARK)
        left_layout.addWidget(self.cursor_info_label)

        # Plot
        self.plot_widget = pg.PlotWidget()
        # Hide Y-axis labels as they are confusing (showing raw FS instead of calibrated Volts)
        self.plot_widget.getPlotItem().getAxis("left").setStyle(showValues=False)
        self.plot_widget.setLabel("bottom", tr("Time"), units="s")
        self.plot_widget.setYRange(self.VIEW_Y_MIN, self.VIEW_Y_MAX)
        self.plot_widget.showGrid(x=True, y=True)

        self.curve_l = self.plot_widget.plot(pen=pg.mkPen("#00ff00", width=2), name=tr("Left"))
        self.curve_r = self.plot_widget.plot(pen=pg.mkPen("#ff0000", width=2), name=tr("Right"))

        # Cursors
        self.cursor_1 = pg.InfiniteLine(
            angle=90, movable=True, pen=pg.mkPen("c", width=1), label="C1", labelOpts={"position": 0.1}
        )
        self.cursor_2 = pg.InfiniteLine(
            angle=90, movable=True, pen=pg.mkPen("m", width=1), label="C2", labelOpts={"position": 0.1}
        )

        self.cursor_1.sigPositionChanged.connect(self.update_cursor_info)
        self.cursor_2.sigPositionChanged.connect(self.update_cursor_info)

        self.plot_widget.addItem(self.cursor_1)
        self.plot_widget.addItem(self.cursor_2)
        self.cursor_1.setVisible(False)
        self.cursor_2.setVisible(False)

        # Persistence Images
        # Let's start with one RGB ImageItem for simplicity of display, we'll compose the heatmap in update_plot.
        self.persistence_img = pg.ImageItem()
        self.plot_widget.addItem(self.persistence_img)
        self.persistence_img.setVisible(False)
        self.persistence_img.setZValue(0)  # Behind cursors

        left_layout.addWidget(self.plot_widget)
        return left_layout

    def _setup_right_panel(self):
        right_widget = QWidget()
        right_widget.setFixedWidth(250)  # Fixed width for controls
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        right_layout.addWidget(tabs)

        tab_controls = QWidget()
        tab_tools_filter = QWidget()

        tabs.addTab(tab_controls, tr("General"))
        tabs.addTab(tab_tools_filter, tr("Tools"))

        controls_layout = QVBoxLayout(tab_controls)
        tools_tab_layout = QVBoxLayout(tab_tools_filter)

        gen_group = QGroupBox(tr("General"))
        gen_layout = QVBoxLayout()
        gen_group.setLayout(gen_layout)
        controls_layout.addWidget(gen_group)

        vert_group = QGroupBox(tr("Vertical"))
        vert_layout = QVBoxLayout()
        vert_group.setLayout(vert_layout)
        controls_layout.addWidget(vert_group)

        trig_group = QGroupBox(tr("Trigger"))
        trig_layout = QVBoxLayout()
        trig_group.setLayout(trig_layout)
        controls_layout.addWidget(trig_group)

        controls_layout.addStretch()

        tools_group = QGroupBox(tr("Tools"))
        tools_layout = QVBoxLayout()
        tools_group.setLayout(tools_layout)
        tools_tab_layout.addWidget(tools_group)

        filter_group = QGroupBox(tr("Filter"))
        filter_layout = QVBoxLayout()
        filter_group.setLayout(filter_layout)
        tools_tab_layout.addWidget(filter_group)

        tools_tab_layout.addStretch()

        self._setup_general_controls(gen_layout)
        self._setup_vertical_controls(vert_layout)
        self._setup_trigger_controls(trig_layout)
        self._setup_tools_controls(tools_layout)
        self._setup_filter_controls(filter_layout)

        return right_widget

    def _setup_general_controls(self, gen_layout):
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

        gen_layout.addWidget(self.toggle_btn)

        # Timebase
        hbox_tb = QHBoxLayout()
        hbox_tb.addWidget(QLabel(tr("Time/Div:")))
        self.timebase_combo = QComboBox()
        self.timebase_options = {
            "10 us": 0.00001,
            "20 us": 0.00002,
            "50 us": 0.00005,
            "100 us": 0.0001,
            "200 us": 0.0002,
            "500 us": 0.0005,
            "1 ms": 0.001,
            "2 ms": 0.002,
            "5 ms": 0.005,
            "10 ms": 0.01,
            "20 ms": 0.02,
            "50 ms": 0.05,
            "100 ms": 0.1,
        }
        self.timebase_keys = list(self.timebase_options.keys())
        self.timebase_combo.addItems(self.timebase_keys)
        self.timebase_combo.setCurrentText("10 ms")
        self.timebase_combo.currentTextChanged.connect(self.on_timebase_changed)
        hbox_tb.addWidget(self.timebase_combo)
        gen_layout.addLayout(hbox_tb)

        # Timebase Slider
        self.timebase_slider = QSlider(Qt.Orientation.Horizontal)
        self.timebase_slider.setRange(0, len(self.timebase_keys) - 1)
        self.timebase_slider.valueChanged.connect(self.on_timebase_slider_changed)
        if "10 ms" in self.timebase_keys:
            self.timebase_slider.setValue(self.timebase_keys.index("10 ms"))
        gen_layout.addWidget(self.timebase_slider)

    def _setup_vertical_controls(self, vert_layout):
        self.vscale_options = {
            "0.01x": 0.01,
            "0.02x": 0.02,
            "0.05x": 0.05,
            "0.1x": 0.1,
            "0.2x": 0.2,
            "0.5x": 0.5,
            "1.0x": 1.0,
            "2.0x": 2.0,
            "5.0x": 5.0,
            "10.0x": 10.0,
            "20.0x": 20.0,
            "50.0x": 50.0,
            "100.0x": 100.0,
            "200.0x": 200.0,
            "500.0x": 500.0,
            "1000.0x": 1000.0,
            "2000.0x": 2000.0,
            "5000.0x": 5000.0,
            "10000.0x": 10000.0,
        }
        self.vscale_keys = list(self.vscale_options.keys())

        hbox_scale_l = QHBoxLayout()
        hbox_scale_l.addWidget(QLabel(tr("Left") + " " + tr("Scale:")))
        self.vscale_combo_l = QComboBox()
        self.vscale_combo_l.addItems(self.vscale_keys)
        self.vscale_combo_l.setCurrentText("1.0x")
        self.vscale_combo_l.currentTextChanged.connect(self.on_vscale_left_changed)
        hbox_scale_l.addWidget(self.vscale_combo_l)
        vert_layout.addLayout(hbox_scale_l)

        self.vscale_slider_l = QSlider(Qt.Orientation.Horizontal)
        self.vscale_slider_l.setRange(0, len(self.vscale_keys) - 1)
        self.vscale_slider_l.valueChanged.connect(self.on_vscale_left_slider_changed)
        if "1.0x" in self.vscale_keys:
            self.vscale_slider_l.setValue(self.vscale_keys.index("1.0x"))
        vert_layout.addWidget(self.vscale_slider_l)

        hbox_scale_r = QHBoxLayout()
        hbox_scale_r.addWidget(QLabel(tr("Right") + " " + tr("Scale:")))
        self.vscale_combo_r = QComboBox()
        self.vscale_combo_r.addItems(self.vscale_keys)
        self.vscale_combo_r.setCurrentText("1.0x")
        self.vscale_combo_r.currentTextChanged.connect(self.on_vscale_right_changed)
        hbox_scale_r.addWidget(self.vscale_combo_r)
        vert_layout.addLayout(hbox_scale_r)

        self.vscale_slider_r = QSlider(Qt.Orientation.Horizontal)
        self.vscale_slider_r.setRange(0, len(self.vscale_keys) - 1)
        self.vscale_slider_r.valueChanged.connect(self.on_vscale_right_slider_changed)
        if "1.0x" in self.vscale_keys:
            self.vscale_slider_r.setValue(self.vscale_keys.index("1.0x"))
        vert_layout.addWidget(self.vscale_slider_r)

        hbox_ch = QHBoxLayout()
        self.chk_left = QCheckBox(tr("Left Ch"))
        self.chk_left.setChecked(True)
        self.chk_left.toggled.connect(lambda x: setattr(self.module, "show_left", x))
        hbox_ch.addWidget(self.chk_left)

        self.chk_right = QCheckBox(tr("Right Ch"))
        self.chk_right.setChecked(True)
        self.chk_right.toggled.connect(lambda x: setattr(self.module, "show_right", x))
        hbox_ch.addWidget(self.chk_right)
        vert_layout.addLayout(hbox_ch)

    def _setup_trigger_controls(self, trig_layout):
        hbox_src = QHBoxLayout()
        hbox_src.addWidget(QLabel(tr("Source:")))
        self.trig_source_combo = QComboBox()
        self.trig_source_combo.addItems([tr("Left"), tr("Right")])
        self.trig_source_combo.currentIndexChanged.connect(self.on_trig_source_changed)
        hbox_src.addWidget(self.trig_source_combo)
        trig_layout.addLayout(hbox_src)

        hbox_slope = QHBoxLayout()
        hbox_slope.addWidget(QLabel(tr("Slope:")))
        self.trig_slope_combo = QComboBox()
        self.trig_slope_combo.addItems([tr("Rising"), tr("Falling")])
        self.trig_slope_combo.currentTextChanged.connect(self.on_trig_slope_changed)
        hbox_slope.addWidget(self.trig_slope_combo)
        trig_layout.addLayout(hbox_slope)

        hbox_mode = QHBoxLayout()
        hbox_mode.addWidget(QLabel(tr("Mode:")))
        self.trig_mode_combo = QComboBox()
        self.trig_mode_combo.addItems([tr("Auto"), tr("Normal"), tr("Single")])
        self.trig_mode_combo.currentTextChanged.connect(self.on_trig_mode_changed)
        hbox_mode.addWidget(self.trig_mode_combo)
        trig_layout.addLayout(hbox_mode)

        hbox_lvl = QHBoxLayout()
        hbox_lvl.addWidget(QLabel(tr("Level:")))
        self.trig_level_spin = QDoubleSpinBox()
        self.trig_level_spin.setRange(-1.0, 1.0)
        self.trig_level_spin.setSingleStep(0.1)
        self.trig_level_spin.setValue(0.0)
        self.trig_level_spin.valueChanged.connect(self.on_trig_level_changed)
        hbox_lvl.addWidget(self.trig_level_spin)
        trig_layout.addLayout(hbox_lvl)

    def _setup_tools_controls(self, tools_layout):
        hbox_math = QHBoxLayout()
        hbox_math.addWidget(QLabel(tr("Math:")))
        self.math_combo = QComboBox()
        self.math_combo.addItems(
            [tr("Off"), tr("A + B"), tr("A - B"), tr("A * B"), tr("A / B"), tr("Derivative"), tr("Integral")]
        )
        self.math_combo.currentTextChanged.connect(self.on_math_changed)
        hbox_math.addWidget(self.math_combo)
        tools_layout.addLayout(hbox_math)

        self.chk_cursors = QCheckBox(tr("Enable Cursors"))
        self.chk_cursors.toggled.connect(self.on_cursors_toggled)
        tools_layout.addWidget(self.chk_cursors)

        self.chk_wave_meas = QCheckBox(tr("Enable Waveform Measurements"))
        self.chk_wave_meas.toggled.connect(self.on_wave_meas_toggled)
        tools_layout.addWidget(self.chk_wave_meas)

        # Persistence Controls
        persist_group = QGroupBox(tr("Persistence"))
        persist_layout = QVBoxLayout()

        self.chk_persist = QCheckBox(tr("Enable Persistence"))
        self.chk_persist.setChecked(self.module.persistence_mode)
        self.chk_persist.toggled.connect(self.on_persist_toggled)
        persist_layout.addWidget(self.chk_persist)

        hbox_decay = QHBoxLayout()
        hbox_decay.addWidget(QLabel(tr("Decay:")))
        self.decay_slider = QSlider(Qt.Orientation.Horizontal)
        self.decay_slider.setRange(0, 99)
        self.decay_slider.setValue(int(self.module.persistence_decay * 100))
        self.decay_slider.valueChanged.connect(self.on_decay_changed)
        hbox_decay.addWidget(self.decay_slider)
        persist_layout.addLayout(hbox_decay)

        hbox_intensity = QHBoxLayout()
        hbox_intensity.addWidget(QLabel(tr("Intensity:")))
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(1, 100)
        self.intensity_slider.setValue(int(self.module.persistence_intensity * 100))
        self.intensity_slider.valueChanged.connect(self.on_intensity_changed)
        hbox_intensity.addWidget(self.intensity_slider)
        persist_layout.addLayout(hbox_intensity)

        persist_group.setLayout(persist_layout)
        tools_layout.addWidget(persist_group)

    def _setup_filter_controls(self, filter_layout):
        hbox_ft = QHBoxLayout()
        hbox_ft.addWidget(QLabel(tr("Type:")))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([tr("None"), tr("LPF"), tr("HPF"), tr("BPF")])
        self.filter_combo.currentTextChanged.connect(self.on_filter_type_changed)
        hbox_ft.addWidget(self.filter_combo)
        filter_layout.addLayout(hbox_ft)

        self.filter_stack = QStackedWidget()

        # None Page
        self.filter_stack.addWidget(QWidget())

        # LPF/HPF Page
        lpf_widget = QWidget()
        lpf_layout = QFormLayout()
        lpf_layout.setContentsMargins(0, 0, 0, 0)
        self.cutoff_spin = QDoubleSpinBox()
        self.cutoff_spin.setRange(10, 24000)
        self.cutoff_spin.setValue(self.module.filter_cutoff)
        self.cutoff_spin.valueChanged.connect(lambda v: setattr(self.module, "filter_cutoff", v))
        lpf_layout.addRow(tr("Cutoff (Hz):"), self.cutoff_spin)
        lpf_widget.setLayout(lpf_layout)
        self.filter_stack.addWidget(lpf_widget)

        # BPF Page
        bpf_widget = QWidget()
        bpf_layout = QFormLayout()
        bpf_layout.setContentsMargins(0, 0, 0, 0)
        self.bpf_low_spin = QDoubleSpinBox()
        self.bpf_low_spin.setRange(10, 24000)
        self.bpf_low_spin.setValue(self.module.filter_low)
        self.bpf_low_spin.valueChanged.connect(lambda v: setattr(self.module, "filter_low", v))
        bpf_layout.addRow(tr("Low (Hz):"), self.bpf_low_spin)

        self.bpf_high_spin = QDoubleSpinBox()
        self.bpf_high_spin.setRange(10, 24000)
        self.bpf_high_spin.setValue(self.module.filter_high)
        self.bpf_high_spin.valueChanged.connect(lambda v: setattr(self.module, "filter_high", v))
        bpf_layout.addRow(tr("High (Hz):"), self.bpf_high_spin)
        bpf_widget.setLayout(bpf_layout)
        self.filter_stack.addWidget(bpf_widget)

        filter_layout.addWidget(self.filter_stack)

    def _setup_math_view(self):
        # Create a new ViewBox for Math
        self.math_view = pg.ViewBox()
        self.plot_widget.plotItem.scene().addItem(self.math_view)
        # Link X axis
        self.math_view.setXLink(self.plot_widget.plotItem)

        # Add Right Axis
        # Remove default right axis if it exists, then add our custom one
        if self.plot_widget.plotItem.getAxis("right") is not None:
            self.plot_widget.plotItem.layout.removeItem(self.plot_widget.plotItem.getAxis("right"))
        self.axis_math = pg.AxisItem("right")
        self.axis_math.linkToView(self.math_view)
        self.axis_math.setLabel(tr("Math"), color="#ffffff")
        self.plot_widget.plotItem.layout.addItem(self.axis_math, 2, 2)  # Row 2, Col 2 for right axis
        self.axis_math.hide()  # Hide by default

        # Update View Geometry on resize
        self.plot_widget.plotItem.vb.sigResized.connect(self.update_math_view_geometry)

        self.curve_math = pg.PlotCurveItem(pen=pg.mkPen("w", width=2, style=Qt.PenStyle.DotLine), name=tr("Math"))
        self.math_view.addItem(self.curve_math)

    def update_math_view_geometry(self):
        # This function ensures the math_view's geometry matches the main plot's viewbox
        # so that the linked X-axis works correctly and the math curve overlays properly.
        self.math_view.setGeometry(self.plot_widget.plotItem.vb.sceneBoundingRect())
        # This line is crucial for the linked X-axis to update its range when the main plot's X-axis changes.
        self.math_view.linkedViewChanged(self.plot_widget.plotItem.vb, self.math_view.XAxis)

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start"))

    def on_timebase_changed(self, text):
        val = self.timebase_options[text]
        # We display 10 divisions usually. So window is 10 * val
        self.module.timebase = val * 10
        self.plot_widget.setXRange(0, self.module.timebase)
        if self.module.persistence_mode:
            self.module.reset_persistence()

        # Sync slider
        self._sync_slider_from_combo(text, self.timebase_keys, self.timebase_slider)

    def _sync_combo_from_slider(self, idx, keys, combo):
        """Helper to sync combo box when slider changes."""
        if 0 <= idx < len(keys):
            key = keys[idx]
            if combo.currentText() != key:
                combo.setCurrentText(key)

    def _sync_slider_from_combo(self, text, keys, slider):
        """Helper to sync slider when combo box changes."""
        if text in keys:
            idx = keys.index(text)
            if slider.value() != idx:
                slider.setValue(idx)

    def _handle_vscale_changed(self, text, attr_name, slider):
        """Helper to handle vertical scale changes."""
        if text not in self.vscale_options:
            return
        scale = float(self.vscale_options[text])
        setattr(self.module, attr_name, scale)
        if self.module.persistence_mode:
            self.module.reset_persistence()

        self._sync_slider_from_combo(text, self.vscale_keys, slider)

    def on_timebase_slider_changed(self, idx):
        self._sync_combo_from_slider(idx, self.timebase_keys, self.timebase_combo)

    def on_vscale_left_slider_changed(self, idx):
        self._sync_combo_from_slider(idx, self.vscale_keys, self.vscale_combo_l)

    def on_vscale_left_changed(self, text):
        self._handle_vscale_changed(text, "vscale_left", self.vscale_slider_l)

    def on_vscale_right_slider_changed(self, idx):
        self._sync_combo_from_slider(idx, self.vscale_keys, self.vscale_combo_r)

    def on_vscale_right_changed(self, text):
        self._handle_vscale_changed(text, "vscale_right", self.vscale_slider_r)

    def on_trig_source_changed(self, index):
        self.module.trigger_source = index

    def on_trig_slope_changed(self, text):
        self.module.trigger_slope = text

    def on_trig_mode_changed(self, text):
        text_to_mode = {
            tr("Auto"): "Auto",
            tr("Normal"): "Normal",
            tr("Single"): "Single",
            "Auto": "Auto",
            "Normal": "Normal",
            "Single": "Single",
        }
        mode = text_to_mode.get(text, text)
        self.module.trigger_mode = mode

        if mode == "Single":
            self.module.single_shot_armed = True
            self.module.single_shot_fired = False
        else:
            self.module.single_shot_armed = False
            self.module.single_shot_fired = False

    def on_trig_level_changed(self, val):
        self.module.trigger_level = val
        # self.trig_line.setPos(val)

        self.module.trigger_level = val

    def on_math_changed(self, val):
        self.module.math_mode = val
        if val == "Off":
            self.axis_math.hide()
            self.curve_math.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead  # Clear math curve when off
        else:
            self.axis_math.show()
            self.axis_math.setLabel(tr("Math ({0})").format(val), color="#ffffff")

    def on_cursors_toggled(self, checked):
        self.cursor_1.setVisible(checked)
        self.cursor_2.setVisible(checked)
        if checked:
            # Initialize positions if needed
            if self.cursor_1.value() == 0 and self.cursor_2.value() == 0:
                x_range = self.plot_widget.viewRange()[0]
                center = (x_range[1] + x_range[0]) / 2
                width = x_range[1] - x_range[0]
                self.cursor_1.setPos(center - width / 4)
                self.cursor_2.setPos(center + width / 4)
        self.update_cursor_info()

    def on_wave_meas_toggled(self, checked):
        self.meas_l_auto_label.setVisible(checked and self.module.show_left)
        self.meas_r_auto_label.setVisible(checked and self.module.show_right)

        if not checked:
            self.meas_l_auto_label.setText(tr("Freq") + ": --  " + tr("Rise") + ": --  " + tr("Fall") + ": --")
            self.meas_r_auto_label.setText(tr("Freq") + ": --  " + tr("Rise") + ": --  " + tr("Fall") + ": --")

    def update_cursor_info(self):
        if not self.chk_cursors.isChecked():
            self.cursor_info_label.setText(tr("Cursors: Off"))
            return

        t1 = self.cursor_1.value()
        t2 = self.cursor_2.value()
        dt = t2 - t1
        freq = 1.0 / abs(dt) if dt != 0 else 0.0

        # Get Voltage at cursors (Interpolate)
        # We need the current data to do this.
        # Since this is called on move, we might not have the exact latest data object here easily
        # without storing it. Let's store the latest displayed data in self.latest_data

        v1_str = ""
        v2_str = ""
        dv_str = ""

        if hasattr(self, "latest_data") and self.latest_data is not None:
            data = self.latest_data
            t = self.latest_t

            # Interpolate
            # Assuming Channel 0 (Left) is primary for cursor measurement if both active,
            # or use Trigger Source? Let's use Trigger Source or just Left.
            # Let's use the first visible channel.

            target_data = None
            if self.module.show_left:
                target_data = data[:, 0]
            elif self.module.show_right:
                target_data = data[:, 1]

            if target_data is not None:
                v1 = np.interp(t1, t, target_data)
                v2 = np.interp(t2, t, target_data)
                dv = v2 - v1
                v1_str = tr("V1: {0:.3f}V").format(v1)
                v2_str = tr("V2: {0:.3f}V").format(v2)
                dv_str = tr("dV: {0:.3f}V").format(dv)

        self.cursor_info_label.setText(
            tr("T1: {0:.2f}ms {1} | T2: {2:.2f}ms {3} | dT: {4:.2f}ms ({5:.1f}Hz) | {6}").format(
                t1 * 1000, v1_str, t2 * 1000, v2_str, dt * 1000, freq, dv_str
            )
        )

    def on_filter_type_changed(self, text):
        self.module.filter_type = text
        if text == "None":
            self.filter_stack.setCurrentIndex(0)
        elif text == "BPF":
            self.filter_stack.setCurrentIndex(2)
        else:
            self.filter_stack.setCurrentIndex(1)  # LPF/HPF share same widget

    def on_persist_toggled(self, checked):
        self.module.persistence_mode = checked
        if checked:
            self.module.reset_persistence()
            self.persistence_img.setVisible(True)
            self.curve_l.setVisible(False)
            self.curve_r.setVisible(False)
        else:
            self.persistence_img.setVisible(False)
            self.curve_l.setVisible(self.module.show_left)
            self.curve_r.setVisible(self.module.show_right)

    def on_decay_changed(self, val):
        self.module.persistence_decay = val / 100.0

    def on_intensity_changed(self, val):
        self.module.persistence_intensity = val / 100.0

    def update_plot(self):
        if not self.module.is_running:
            return

        # Process audio queue first
        self.module.process_queue()

        window_duration = self.module.timebase
        data = self.module.get_display_data(window_duration)

        if data is not None and len(data) > 0:
            # Create time axis
            # Optimization: Cache time array
            current_len = len(data)
            cached_duration, cached_len = self._time_array_cache_params

            if self._time_array_cache is not None and cached_duration == window_duration and cached_len == current_len:
                t = self._time_array_cache
            else:
                t = np.linspace(0, window_duration, current_len)
                self._time_array_cache = t
                self._time_array_cache_params = (window_duration, current_len)

            self.last_display_data = data.copy()
            self.last_display_time = t.copy()

            display_step = max(1, int(np.ceil(current_len / self.module.MAX_DISPLAY_SAMPLES)))

            # Apply Filter if enabled
            sr = self.module.audio_engine.sample_rate
            if self.module.filter_type != "None":
                if self.module.filter_type == "LPF":
                    data[:, 0] = AudioCalc.lowpass_filter(data[:, 0], sr, self.module.filter_cutoff)
                    data[:, 1] = AudioCalc.lowpass_filter(data[:, 1], sr, self.module.filter_cutoff)
                elif self.module.filter_type == "HPF":
                    data[:, 0] = AudioCalc.highpass_filter(data[:, 0], sr, self.module.filter_cutoff)
                    data[:, 1] = AudioCalc.highpass_filter(data[:, 1], sr, self.module.filter_cutoff)
                elif self.module.filter_type == "BPF":
                    data[:, 0] = AudioCalc.bandpass_filter(
                        data[:, 0], sr, self.module.filter_low, self.module.filter_high
                    )
                    data[:, 1] = AudioCalc.bandpass_filter(
                        data[:, 1], sr, self.module.filter_low, self.module.filter_high
                    )

            # Measurements
            l_data = data[:, 0]
            r_data = data[:, 1]

            meas = self.module.get_measurements(data)

            self.meas_l_label.setText(tr("L: Vrms: {0:.3f} V  Vpp: {1:.3f} V").format(meas["l_rms"], meas["l_vpp"]))
            self.meas_r_label.setText(tr("R: Vrms: {0:.3f} V  Vpp: {1:.3f} V").format(meas["r_rms"], meas["r_vpp"]))

            # Waveform-derived measurements (optional)
            wave_meas_enabled = hasattr(self, "chk_wave_meas") and self.chk_wave_meas.isChecked()
            self.meas_l_auto_label.setVisible(wave_meas_enabled and self.module.show_left)
            self.meas_r_auto_label.setVisible(wave_meas_enabled and self.module.show_right)

            if wave_meas_enabled:
                if self.module.show_left:
                    freq_hz = self.module.estimate_frequency_hz(t, l_data)
                    rise_s, fall_s, _low, _high = self.module.estimate_rise_fall_times_s(t, l_data)

                    freq_str = format_si(freq_hz, "Hz", sig_figs=5) if freq_hz is not None and freq_hz > 0 else "--"
                    rise_str = format_si(rise_s, "s", sig_figs=5) if rise_s is not None and rise_s > 0 else "--"
                    fall_str = format_si(fall_s, "s", sig_figs=5) if fall_s is not None and fall_s > 0 else "--"

                    self.meas_l_auto_label.setText(
                        tr("Freq") + f": {freq_str}  " + tr("Rise") + f": {rise_str}  " + tr("Fall") + f": {fall_str}"
                    )
                if self.module.show_right:
                    freq_hz = self.module.estimate_frequency_hz(t, r_data)
                    rise_s, fall_s, _low, _high = self.module.estimate_rise_fall_times_s(t, r_data)

                    freq_str = format_si(freq_hz, "Hz", sig_figs=5) if freq_hz is not None and freq_hz > 0 else "--"
                    rise_str = format_si(rise_s, "s", sig_figs=5) if rise_s is not None and rise_s > 0 else "--"
                    fall_str = format_si(fall_s, "s", sig_figs=5) if fall_s is not None and fall_s > 0 else "--"

                    self.meas_r_auto_label.setText(
                        tr("Freq") + f": {freq_str}  " + tr("Rise") + f": {rise_str}  " + tr("Fall") + f": {fall_str}"
                    )

            # Store for cursor interpolation
            self.latest_data = data
            self.latest_t = t

            plot_t = t[::display_step]
            plot_data = data[::display_step]
            scaled_l = plot_data[:, 0] * float(getattr(self.module, "vscale_left", 1.0))
            scaled_r = plot_data[:, 1] * float(getattr(self.module, "vscale_right", 1.0))

            if self.module.persistence_mode:
                # Update Persistence
                decay = self.module.persistence_decay
                intensity = self.module.persistence_intensity

                # Decay
                self.module.heatmap_l *= decay
                self.module.heatmap_r *= decay

                # Binning
                w, h = self.module.heatmap_size
                # X Range: 0 to window_duration
                # Y Range: Fixed (Plot View)
                # Note: We bin SCALED data.

                rng = [[0, window_duration], [self.VIEW_Y_MIN, self.VIEW_Y_MAX]]

                if self.module.show_left:
                    self.module._accumulate_heatmap(plot_t, scaled_l, self.module.heatmap_l, [w, h], rng, intensity)

                if self.module.show_right:
                    self.module._accumulate_heatmap(plot_t, scaled_r, self.module.heatmap_r, [w, h], rng, intensity)

                # Compose Image
                # L = Green, R = Red
                # Output shape (h, w, 4) (RGBA) or (w, h, 4)?
                # pg.ImageItem takes (w, h) or (h, w) depending on axisOrder.
                # Default is col-major (w, h)?
                # histogram2d returns (nx, ny). T -> (ny, nx) i.e. (h, w).
                # ImageItem expects (width, height) usually if axisOrder='col-major'.
                # Let's check Goniometer: self.img_item.setImage(self.module.heatmap.T)
                # It transposes.
                # If we construct RGBA, we can match direct dimensions.

                # Let's construct RGBA image of shape (w, h, 4)
                # heatmap_l is (h, w) due to Transpose above?
                # heatmap_l shape is (w, h) init.
                # histogram2d(x, y, bins=[w, h]) -> shape (w, h).
                # So hist_l is (w, h).
                # We added hist_l.T -> (h, w)?
                # If we want to map X(time) to X(screen), and Y(amp) to Y(screen).
                # ImageItem:
                # "image data is interpreted as a row-major array (shape=(height, width))" IF axisOrder='row-major'.
                # Default is 'col-major' (width, height).
                # Let's stick to (w, h) if default.

                # Reset buffers to not Transpose if we want (w, h).
                # self.module.heatmap_l is initialized as (w, h).
                # hist_l is (w, h).
                # So: self.module.heatmap_l += hist_l * intensity.

                # But wait, y axis in numpy is usually index 0 or 1?
                # histogram2d returns H[x, y].
                # So H[0,0] is x=min, y=min.
                # If ImageItem expects data[x, y], then we are good.

                w, h = self.module.heatmap_size
                if self._rgba_buffer is None or self._rgba_buffer.shape[:2] != (w, h):
                    self._rgba_buffer = np.zeros((w, h, 4), dtype=np.ubyte)
                    self._clip_buffer = np.empty((w, h), dtype=self.module.heatmap_l.dtype)

                # Clip and map to 0-255
                # Green (Left)
                np.clip(self.module.heatmap_l, 0, 255, out=self._clip_buffer)
                self._rgba_buffer[..., 1] = self._clip_buffer.astype(np.ubyte)

                # Red (Right)
                np.clip(self.module.heatmap_r, 0, 255, out=self._clip_buffer)
                self._rgba_buffer[..., 0] = self._clip_buffer.astype(np.ubyte)

                # B is 0 (untouched from init)
                # Alpha: Max of L/R
                np.maximum(
                    self._rgba_buffer[..., 1],
                    self._rgba_buffer[..., 0],
                    out=self._rgba_buffer[..., 3],
                )

                self.persistence_img.setImage(self._rgba_buffer, autoLevels=False)
                self.persistence_img.setRect(
                    pg.QtCore.QRectF(0, self.VIEW_Y_MIN, window_duration, self.VIEW_Y_MAX - self.VIEW_Y_MIN)
                )

                # Hide curves
                self.curve_l.setVisible(False)
                self.curve_r.setVisible(False)

            else:
                # Normal Mode
                if self.module.show_left:
                    self.curve_l.setData(plot_t, scaled_l)
                    self.curve_l.setVisible(True)
                else:
                    self.curve_l.setVisible(False)

                if self.module.show_right:
                    self.curve_r.setData(plot_t, scaled_r)
                    self.curve_r.setVisible(True)
                else:
                    self.curve_r.setVisible(False)

                self.persistence_img.setVisible(False)

            # Math Processing
            if self.module.math_mode != "Off":
                math_data = None

                # A = Left, B = Right
                A = data[:, 0]
                B = data[:, 1]

                mode = self.module.math_mode

                if mode == "A + B":
                    math_data = A + B
                elif mode == "A - B":
                    math_data = A - B
                elif mode == "A * B":
                    math_data = A * B
                elif mode == "A / B":
                    # Avoid division by zero
                    with np.errstate(divide="ignore", invalid="ignore"):
                        math_data = np.divide(A, B)
                        math_data[~np.isfinite(math_data)] = 0  # Replace inf/nan with 0
                elif mode == "Derivative":  # Derivative of A (Left)
                    dt = t[1] - t[0] if len(t) > 1 else 1e-6
                    math_data = np.gradient(A, dt)
                elif mode == "Integral":  # Integral of A (Left)
                    dt = t[1] - t[0] if len(t) > 1 else 1e-6
                    math_data = np.cumsum(A) * dt
                    math_data = math_data - np.mean(math_data)

                if math_data is not None and math_data.size > 0:
                    self.curve_math.setData(plot_t, math_data[::display_step])
                    # Auto-scale Math View
                    mn, mx = np.min(math_data), np.max(math_data)
                    if mn == mx:
                        mn -= 0.1
                        mx += 0.1
                    padding = (mx - mn) * 0.1
                    self.math_view.setYRange(mn - padding, mx + padding)
                else:
                    self.curve_math.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead
            else:
                self.curve_math.clear()  # Performance: Use clear() instead of setData([], []) to avoid list parsing overhead

            # Update cursor info if they are on (to update voltage readings)
            if self.chk_cursors.isChecked():
                self.update_cursor_info()

            # Single-shot mode: stop updates immediately after the first trigger capture.
            if self.module.trigger_mode == "Single" and self.module.single_shot_fired:
                self.timer.stop()
                self.module.stop_analysis()
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.setText(tr("Start"))
                self.toggle_btn.blockSignals(False)

    def apply_theme(self, theme_name):
        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            # Dark Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_DARK)
            self.meas_l_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
            self.meas_r_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
            if hasattr(self, "meas_l_auto_label"):
                self.meas_l_auto_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
            if hasattr(self, "meas_r_auto_label"):
                self.meas_r_auto_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
            self.cursor_info_label.setStyleSheet(STYLE_LABEL_CURSOR_DARK)
        else:
            # Light Theme
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)
            self.meas_l_label.setStyleSheet(STYLE_LABEL_LEFT_CH_LIGHT)
            self.meas_r_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_LIGHT)
            if hasattr(self, "meas_l_auto_label"):
                self.meas_l_auto_label.setStyleSheet(STYLE_LABEL_LEFT_CH_LIGHT)
            if hasattr(self, "meas_r_auto_label"):
                self.meas_r_auto_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_LIGHT)
            self.cursor_info_label.setStyleSheet(STYLE_LABEL_CURSOR_LIGHT)

    def update_compact_layout(self):
        compact = self.is_compact_mode()
        if hasattr(self, "right_widget"):
            self.right_widget.setHidden(compact)
        if hasattr(self, "meas_group"):
            self.meas_group.setHidden(compact)
        if hasattr(self, "cursor_info_label"):
            self.cursor_info_label.setHidden(compact)

    def get_comparable_data(self) -> List[ComparisonTrace]:
        if self.last_display_data is None or self.last_display_time is None:
            return []

        import uuid
        from datetime import datetime

        data = self.last_display_data
        t = self.last_display_time

        try:
            input_sensitivity = self.module.audio_engine.calibration.input_sensitivity
            is_calibrated = self.module.audio_engine.calibration.is_calibrated
        except Exception:
            input_sensitivity = 1.0
            is_calibrated = False

        timestamp = datetime.now().isoformat()
        traces = []

        # Left channel
        if self.module.show_left:
            trace_id = str(uuid.uuid4())
            trace_name = f"{tr('Oscilloscope')} - L ({datetime.now().strftime('%H:%M:%S')})"

            x_axis = AxisMetadata(dimension="time", base_unit="s", display_unit="s", is_log=False)

            if is_calibrated:
                y_axis = AxisMetadata(dimension="voltage", base_unit="V", display_unit="V", is_log=False)
                y_data = (data[:, 0] * input_sensitivity).tolist()
                ref_lvl = "absolute"
            else:
                y_axis = AxisMetadata(dimension="voltage", base_unit="FS", display_unit="FS", is_log=False)
                y_data = data[:, 0].tolist()
                ref_lvl = "relative"

            trace_l = ComparisonTrace(
                id=trace_id,
                name=trace_name,
                source_module="Oscilloscope",
                timestamp=timestamp,
                plot_type="time_series",
                x_axis=x_axis,
                y_axis=y_axis,
                x_data=t.tolist(),
                y_data=y_data,
                calibration=CalibrationInfo(
                    is_calibrated=is_calibrated,
                    input_sensitivity=input_sensitivity,
                    applied_offset_db=0.0,
                    reference_level=ref_lvl,
                ),
                metadata={
                    "channel": "Left",
                    "timebase": self.module.timebase,
                },
            )
            traces.append(trace_l)

        # Right channel
        if self.module.show_right:
            trace_id = str(uuid.uuid4())
            trace_name = f"{tr('Oscilloscope')} - R ({datetime.now().strftime('%H:%M:%S')})"

            x_axis = AxisMetadata(dimension="time", base_unit="s", display_unit="s", is_log=False)

            if is_calibrated:
                y_axis = AxisMetadata(dimension="voltage", base_unit="V", display_unit="V", is_log=False)
                y_data = (data[:, 1] * input_sensitivity).tolist()
                ref_lvl = "absolute"
            else:
                y_axis = AxisMetadata(dimension="voltage", base_unit="FS", display_unit="FS", is_log=False)
                y_data = data[:, 1].tolist()
                ref_lvl = "relative"

            trace_r = ComparisonTrace(
                id=trace_id,
                name=trace_name,
                source_module="Oscilloscope",
                timestamp=timestamp,
                plot_type="time_series",
                x_axis=x_axis,
                y_axis=y_axis,
                x_data=t.tolist(),
                y_data=y_data,
                calibration=CalibrationInfo(
                    is_calibrated=is_calibrated,
                    input_sensitivity=input_sensitivity,
                    applied_offset_db=0.0,
                    reference_level=ref_lvl,
                ),
                metadata={
                    "channel": "Right",
                    "timebase": self.module.timebase,
                },
            )
            traces.append(trace_r)

        return traces
