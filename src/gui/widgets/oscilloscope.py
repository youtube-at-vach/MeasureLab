import logging
from typing import List, Optional

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
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.comparison_manager import AxisMetadata, CalibrationInfo, ComparisonTrace
from src.core.localization import tr
from src.core.ring_buffer import RingBuffer
from src.core.utils import format_si
from src.gui.styles import (
    STYLE_LABEL_CURSOR_DARK,
    STYLE_LABEL_CURSOR_LIGHT,
    STYLE_LABEL_LEFT_CH_DARK,
    STYLE_LABEL_LEFT_CH_LIGHT,
    STYLE_LABEL_RIGHT_CH_DARK,
    STYLE_LABEL_RIGHT_CH_LIGHT,
    STYLE_TOGGLE_BTN_DARK,
    STYLE_TOGGLE_BTN_LIGHT,
)
from src.gui.widgets.compactable_interface import CompactableWidgetInterface
from src.gui.widgets.comparable_interface import ComparableWidgetInterface
from src.gui.widgets.splittable_interface import SplittableWidgetInterface
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class Oscilloscope(MeasurementModule):
    MIN_BUFFER_SIZE = 8192
    MAX_DISPLAY_SAMPLES = 8192
    TRIGGER_SEARCH_WINDOW_SIZE = 2048
    TRIGGER_SEARCH_FRACTION = 0.25
    MAX_TRIGGER_SEARCH_WINDOW_SIZE = 8192

    # Standard 1-2-5 step sequences for Time/Div and Vertical Scale (per division)
    TIME_DIV_OPTIONS = [
        ("10 us", 0.00001),
        ("20 us", 0.00002),
        ("50 us", 0.00005),
        ("100 us", 0.0001),
        ("200 us", 0.0002),
        ("500 us", 0.0005),
        ("1 ms", 0.001),
        ("2 ms", 0.002),
        ("5 ms", 0.005),
        ("10 ms", 0.01),
        ("20 ms", 0.02),
        ("50 ms", 0.05),
        ("100 ms", 0.1),
        ("200 ms", 0.2),
        ("500 ms", 0.5),
    ]

    VDIV_OPTIONS_UNCALIBRATED = [
        ("1 mFS", 0.001),
        ("2 mFS", 0.002),
        ("5 mFS", 0.005),
        ("10 mFS", 0.01),
        ("20 mFS", 0.02),
        ("50 mFS", 0.05),
        ("100 mFS", 0.1),
        ("200 mFS", 0.2),
        ("250 mFS", 0.25),
        ("500 mFS", 0.5),
        ("1 FS", 1.0),
    ]

    VDIV_OPTIONS_CALIBRATED = [
        ("1 mV", 0.001),
        ("2 mV", 0.002),
        ("5 mV", 0.005),
        ("10 mV", 0.01),
        ("20 mV", 0.02),
        ("50 mV", 0.05),
        ("100 mV", 0.1),
        ("200 mV", 0.2),
        ("500 mV", 0.5),
        ("1 V", 1.0),
        ("2 V", 2.0),
        ("5 V", 5.0),
        ("10 V", 10.0),
        ("20 V", 20.0),
    ]

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False

        # Horizontal timebase (Total view duration = 10 * time_div)
        self.time_div = 0.001  # 1 ms/div (default 10 ms window)
        self.timebase = self.time_div * 10.0  # Seconds total window

        # Buffer allocation
        self.buffer_size = self._recommended_buffer_size(self.timebase)
        self.input_data = np.zeros((self.buffer_size * 2, 2))
        self.write_index = 0

        self.gain = 1.0
        self.trigger_source = 0  # 0: Left, 1: Right
        self.trigger_mode = "Auto"  # 'Auto', 'Normal', 'Single'
        self.trigger_slope = "Rising"  # 'Rising', 'Falling'
        self.trigger_level = 0.0  # Trigger level in active units (FS or Volts)
        self.show_left = True
        self.show_right = True
        self.show_x_axis = False

        # Vertical sensitivity per channel (units per division)
        self.vdiv_left = 0.25
        self.vdiv_right = 0.25

        # Overload / Clipping detection & latching (T&M Failsafe)
        self.clipping_detected_l = False
        self.clipping_detected_r = False
        self.clipping_latched_l = False
        self.clipping_latched_r = False

        # Single-shot trigger state
        self.single_shot_armed = False
        self.single_shot_fired = False

        # Math Mode
        self.math_mode = "Off"  # 'Off', 'A + B', 'A - B', 'A * B', 'A / B', 'Derivative', 'Integral'

        # Filter Settings
        self.filter_type = "None"  # 'None', 'LPF', 'HPF', 'BPF'
        self.filter_cutoff = 1000.0  # For LPF/HPF
        self.filter_low = 1000.0  # For BPF
        self.filter_high = 2000.0  # For BPF

        # Persistence Settings
        self.persistence_mode = False
        self.persistence_decay = 0.90
        self.persistence_intensity = 0.5
        self.heatmap_l = None
        self.heatmap_r = None
        self.heatmap_size = (600, 400)

        # High-performance transfer buffer (Ring Buffer)
        self.transfer_buffer_size = 65536
        self.transfer_buffer = RingBuffer(self.transfer_buffer_size, 2, dtype=np.float32)

        self.callback_id = None

    @property
    def vscale_left(self) -> float:
        """Multiplier representation of vertical scale for backward compatibility."""
        if self.vdiv_left <= 0:
            return 1.0
        return 0.25 / self.vdiv_left

    @vscale_left.setter
    def vscale_left(self, val: float):
        if val > 0:
            self.vdiv_left = 0.25 / val

    @property
    def vscale_right(self) -> float:
        """Multiplier representation of vertical scale for backward compatibility."""
        if self.vdiv_right <= 0:
            return 1.0
        return 0.25 / self.vdiv_right

    @vscale_right.setter
    def vscale_right(self, val: float):
        if val > 0:
            self.vdiv_right = 0.25 / val

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

        x_scale = w / (x_max - x_min)
        y_scale = h / (y_max - y_min)

        mask = (y >= y_min) & (y <= y_max)
        if not np.any(mask):
            return

        y_valid = y[mask]
        t_valid = t[mask]

        x_idx = ((t_valid - x_min) * x_scale).astype(np.int32)
        y_idx = ((y_valid - y_min) * y_scale).astype(np.int32)

        x_idx[x_idx == w] = w - 1
        y_idx[y_idx == h] = h - 1

        np.clip(x_idx, 0, w - 1, out=x_idx)
        np.clip(y_idx, 0, h - 1, out=y_idx)

        np.add.at(heatmap, (x_idx, y_idx), intensity * 100)

    def get_widget(self):
        return OscilloscopeWidget(self)

    def reset_persistence(self):
        w, h = self.heatmap_size
        self.heatmap_l = np.zeros((w, h))
        self.heatmap_r = np.zeros((w, h))

    def reset_clipping_latch(self):
        """Reset the overload/clipping latch for new measurement runs."""
        self.clipping_detected_l = False
        self.clipping_detected_r = False
        self.clipping_latched_l = False
        self.clipping_latched_r = False

    def check_clipping(self, data: np.ndarray) -> None:
        """Check if incoming audio data reached full-scale (0 dBFS) or contains non-finite values."""
        if data is None or len(data) == 0:
            self.clipping_detected_l = False
            self.clipping_detected_r = False
            return

        l_data = data[:, 0]
        r_data = data[:, 1]

        clip_l = bool(np.any(np.abs(l_data) >= 0.999) or not np.all(np.isfinite(l_data)))
        clip_r = bool(np.any(np.abs(r_data) >= 0.999) or not np.all(np.isfinite(r_data)))

        self.clipping_detected_l = clip_l
        self.clipping_detected_r = clip_r

        if clip_l:
            self.clipping_latched_l = True
        if clip_r:
            self.clipping_latched_r = True

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
        self.reset_clipping_latch()
        self._ensure_buffer_capacity(self.timebase)
        self.input_data = np.zeros((self.buffer_size * 2, 2))
        self.write_index = 0

        self.transfer_buffer.reset()

        if self.persistence_mode:
            self.reset_persistence()

        if self.trigger_mode == "Single":
            self.single_shot_armed = True
            self.single_shot_fired = False

        def callback(indata, outdata, frames, time, status):
            if status:
                logger.debug(status)
            self.transfer_buffer.write(indata)
            outdata.fill(0)

        self.callback_id = self.audio_engine.register_callback(callback)

    def process_queue(self):
        new_data = self.transfer_buffer.read()
        n_frames = len(new_data)
        if n_frames == 0:
            return

        # Check clipping on streaming input
        self.check_clipping(new_data)

        if n_frames > self.buffer_size:
            last_part = new_data[-self.buffer_size :]
            self.input_data[: self.buffer_size] = last_part
            self.input_data[self.buffer_size :] = last_part
            self.write_index = 0
        else:
            idx = self.write_index
            end_idx = idx + n_frames
            if end_idx <= self.buffer_size:
                self.input_data[idx:end_idx] = new_data
                self.input_data[idx + self.buffer_size : end_idx + self.buffer_size] = new_data
            else:
                part1_len = self.buffer_size - idx
                self.input_data[idx : self.buffer_size] = new_data[:part1_len]
                self.input_data[idx + self.buffer_size :] = new_data[:part1_len]

                part2_len = n_frames - part1_len
                self.input_data[:part2_len] = new_data[part1_len:]
                self.input_data[self.buffer_size : self.buffer_size + part2_len] = new_data[part1_len:]

            self.write_index = (idx + n_frames) % self.buffer_size

    def get_measurements(self, data):
        """Calculate RMS and peak-to-peak amplitude in the active display unit."""
        _is_calibrated, amplitude_factor, _unit = self.get_amplitude_display_state()

        if data is None or len(data) == 0:
            return {"l_rms": 0.0, "l_vpp": 0.0, "r_rms": 0.0, "r_vpp": 0.0}

        l_data = data[:, 0]
        r_data = data[:, 1]

        l_rms = np.sqrt(np.mean(l_data**2)) * amplitude_factor
        r_rms = np.sqrt(np.mean(r_data**2)) * amplitude_factor

        l_vpp = (np.max(l_data) - np.min(l_data)) * amplitude_factor
        r_vpp = (np.max(r_data) - np.min(r_data)) * amplitude_factor

        return {"l_rms": l_rms, "l_vpp": l_vpp, "r_rms": r_rms, "r_vpp": r_vpp}

    def get_amplitude_display_state(self):
        """Return (is_calibrated, scale_factor, unit) for amplitude readouts."""
        try:
            calibration = self.audio_engine.calibration
            calibrated_flag = getattr(calibration, "input_sensitivity_is_calibrated", None)
            if not isinstance(calibrated_flag, (bool, np.bool_)):
                calibrated_flag = getattr(calibration, "is_calibrated", False)

            is_calibrated = isinstance(calibrated_flag, (bool, np.bool_)) and bool(calibrated_flag)
            sensitivity = float(calibration.input_sensitivity)
            if not np.isfinite(sensitivity) or sensitivity <= 0:
                raise ValueError("Invalid input sensitivity")
        except Exception:
            return False, 1.0, "FS"

        if not is_calibrated:
            return False, 1.0, "FS"
        return True, sensitivity, "V"

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

    def _get_data_slice(self, start_offset, length):
        """Returns a contiguous array of length samples starting at logical offset start_offset."""
        if length <= 0:
            return np.empty((0, 2))

        idx = (self.write_index + start_offset) % self.buffer_size
        end_idx = idx + length

        return self.input_data[idx:end_idx].copy()

    def get_display_data(self, window_duration):
        """Get triggered data for display."""
        self._ensure_buffer_capacity(window_duration)
        sample_rate = self._sample_rate_hz()
        required_samples = int(window_duration * sample_rate)

        if required_samples > self.buffer_size:
            required_samples = self.buffer_size

        if self.trigger_mode == "Single" and not self.single_shot_armed:
            return None

        search_end = self.buffer_size - required_samples
        if search_end <= 0:
            start_offset = max(0, self.buffer_size - required_samples)
            return self._get_data_slice(start_offset, required_samples)

        search_window = self._recommended_trigger_search_window(required_samples)
        start_idx = max(0, search_end - search_window)

        search_length = search_end - start_idx
        subset_data = self._get_data_slice(start_idx, search_length)
        subset = subset_data[:, self.trigger_source]

        _is_calibrated, factor, _ = self.get_amplitude_display_state()
        threshold_fs = self.trigger_level / factor if _is_calibrated and factor > 0 else self.trigger_level

        if self.trigger_slope == "Rising":
            crossings = np.where((subset[:-1] < threshold_fs) & (subset[1:] >= threshold_fs))[0]
        else:
            crossings = np.where((subset[:-1] > threshold_fs) & (subset[1:] <= threshold_fs))[0]

        if len(crossings) > 0:
            trigger_offset_in_subset = crossings[-1] + 1
            trigger_idx = start_idx + trigger_offset_in_subset

            if self.trigger_mode == "Single":
                self.single_shot_fired = True
                self.single_shot_armed = False

            return self._get_data_slice(trigger_idx, required_samples)
        else:
            if self.trigger_mode == "Auto":
                start_offset = self.buffer_size - required_samples
                return self._get_data_slice(start_offset, required_samples)
            else:
                return None

    @staticmethod
    def estimate_frequency_hz(t: np.ndarray, y: np.ndarray) -> Optional[float]:
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
        """Estimate 10-90% rise time and 90-10% fall time for step-like waveforms."""
        if t is None or y is None or len(t) < 4:
            return (None, None, None, None)

        yy = np.asarray(y, dtype=float)
        tt = np.asarray(t, dtype=float)
        if yy.size != tt.size:
            return (None, None, None, None)

        low_q = float(np.percentile(yy, 10))
        high_q = float(np.percentile(yy, 90))
        if not np.isfinite(low_q) or not np.isfinite(high_q):
            return (None, None, None, None)

        low_level = min(low_q, high_q)
        high_level = max(low_q, high_q)
        amp = high_level - low_level
        if amp <= 1e-9:
            return (None, None, low_level, high_level)

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

    def auto_scale(self, data: Optional[np.ndarray] = None) -> bool:
        """
        Auto Scale (Auto Set) engine for Oscilloscope.
        Analyzes the current signal amplitude and frequency to automatically select
        optimal Time/Div, Vertical Scale (V/div or FS/div), and Trigger parameters.
        """
        if data is None or len(data) == 0:
            window_duration = self.timebase
            data = self._get_data_slice(0, min(self.buffer_size, int(window_duration * self._sample_rate_hz())))

        if data is None or len(data) < 16:
            return False

        sr = self._sample_rate_hz()
        t = np.arange(len(data)) / sr

        l_data = data[:, 0]
        r_data = data[:, 1]

        l_vpp_fs = float(np.max(l_data) - np.min(l_data))
        r_vpp_fs = float(np.max(r_data) - np.min(r_data))

        primary_ch = 0 if l_vpp_fs >= r_vpp_fs else 1
        self.trigger_source = primary_ch
        primary_data = l_data if primary_ch == 0 else r_data

        is_calibrated, factor, _ = self.get_amplitude_display_state()

        target_div = 5.0
        vdiv_options = [val for _, val in (self.VDIV_OPTIONS_CALIBRATED if is_calibrated else self.VDIV_OPTIONS_UNCALIBRATED)]

        for _ch_idx, (vpp_fs, attr_name) in enumerate([(l_vpp_fs, "vdiv_left"), (r_vpp_fs, "vdiv_right")]):
            vpp = vpp_fs * factor if is_calibrated else vpp_fs
            if vpp < 1e-4:
                best_vdiv = 0.2 if not is_calibrated else 0.5
            else:
                desired_vdiv = vpp / target_div
                candidates = [opt for opt in vdiv_options if opt >= desired_vdiv * 0.9]
                best_vdiv = candidates[0] if candidates else vdiv_options[-1]
            setattr(self, attr_name, best_vdiv)

        freq = self.estimate_frequency_hz(t, primary_data)
        time_div_options = [val for _, val in self.TIME_DIV_OPTIONS]

        if freq is not None and freq > 5.0:
            period = 1.0 / freq
            desired_time_div = (3.0 * period) / 10.0
            candidates = [opt for opt in time_div_options if opt >= desired_time_div * 0.8]
            best_time_div = candidates[0] if candidates else time_div_options[-1]
        else:
            best_time_div = 0.001

        self.time_div = best_time_div
        self.timebase = best_time_div * 10.0

        self.trigger_mode = "Auto"
        self.trigger_slope = "Rising"
        self.trigger_level = 0.0

        return True


class OscilloscopeWidget(QWidget, CompactableWidgetInterface, ComparableWidgetInterface, SplittableWidgetInterface):
    VIEW_Y_MIN = -4.0
    VIEW_Y_MAX = 4.0

    def __init__(self, module: Oscilloscope):
        QWidget.__init__(self)
        CompactableWidgetInterface.__init__(self)
        ComparableWidgetInterface.__init__(self)
        SplittableWidgetInterface.__init__(self)
        self.module = module
        self._rgba_buffer = None
        self._clip_buffer = None
        self.last_display_data = None
        self.last_display_time = None
        self._updating_trigger_line = False

        self._time_array_cache = None
        self._time_array_cache_params = (None, None)

        self._math_autofit_pending = False

        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.setInterval(30)

    @property
    def timebase_options(self):
        """Dictionary of timebase options for backward compatibility."""
        return dict(self.module.TIME_DIV_OPTIONS)

    @property
    def timebase_keys(self):
        """List of timebase option keys for backward compatibility."""
        return [lbl for lbl, _ in self.module.TIME_DIV_OPTIONS]

    @property
    def vscale_options(self):
        """Dictionary of vertical scale options for backward compatibility."""
        return dict(self._get_active_vdiv_options())

    @property
    def vscale_keys(self):
        """List of vertical scale option keys for backward compatibility."""
        return [lbl for lbl, _ in self._get_active_vdiv_options()]

    def closeEvent(self, event: QCloseEvent):
        self.timer.stop()
        self.module.stop_analysis()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_scale_combos()
        self._update_calibration_status()
        if hasattr(self, "latest_data") and self.latest_data is not None:
            self._set_measurement_labels(self.module.get_measurements(self.latest_data))
            if self.chk_cursors.isChecked():
                self.update_cursor_info()

    def get_display_widget(self) -> QWidget:
        return self.display_widget

    def get_control_widget(self) -> QWidget:
        return self.right_widget

    def restore_split_panels(self) -> None:
        layout = self.layout()
        if layout is None:
            return
        layout.addWidget(self.display_widget, stretch=1)
        layout.addWidget(self.right_widget)
        self.display_widget.show()
        self.right_widget.show()

    def init_ui(self):
        main_layout = QHBoxLayout()

        self.display_widget = self._setup_left_panel()
        main_layout.addWidget(self.display_widget, stretch=1)

        self.right_widget = self._setup_right_panel()

        self._setup_math_view()

        main_layout.addWidget(self.right_widget)
        self.setLayout(main_layout)

    def _setup_left_panel(self) -> QWidget:
        display_widget = QWidget()
        left_layout = QVBoxLayout(display_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Badge & Status Header
        self.badge_group = QGroupBox()
        self.badge_group.setStyleSheet("QGroupBox { border: 1px solid #3d4450; border-radius: 4px; margin-top: 0px; padding: 2px; }")
        badge_layout = QHBoxLayout(self.badge_group)
        badge_layout.setContentsMargins(4, 2, 4, 2)
        badge_layout.setSpacing(4)

        self.badge_l_label = QLabel()
        self.badge_l_label.setStyleSheet("QLabel { color: #00ff00; font-weight: bold; background: #16241a; padding: 2px 4px; border-radius: 3px; border: 1px solid #00aa00; font-size: 11px; }")
        badge_layout.addWidget(self.badge_l_label)

        self.badge_r_label = QLabel()
        self.badge_r_label.setStyleSheet("QLabel { color: #ff5555; font-weight: bold; background: #2b1818; padding: 2px 4px; border-radius: 3px; border: 1px solid #aa0000; font-size: 11px; }")
        badge_layout.addWidget(self.badge_r_label)

        self.badge_status_label = QLabel()
        self.badge_status_label.setStyleSheet("QLabel { color: #d0d7de; font-weight: normal; padding: 2px 4px; font-size: 11px; }")
        badge_layout.addWidget(self.badge_status_label)

        badge_layout.addStretch()

        self.calibration_status_label = QLabel()
        self.calibration_status_label.setStyleSheet("QLabel { color: #8b949e; font-size: 10px; }")
        badge_layout.addWidget(self.calibration_status_label)

        self.clipping_warning_badge = QLabel(tr("CLIPPING"))
        self.clipping_warning_badge.setStyleSheet(
            "QLabel { color: #ffffff; background-color: #d73a49; font-weight: bold; padding: 2px 6px; border-radius: 3px; font-size: 10px; }"
        )
        self.clipping_warning_badge.setVisible(False)
        badge_layout.addWidget(self.clipping_warning_badge)

        left_layout.addWidget(self.badge_group)

        # Measurements Panel
        self.meas_group = QGroupBox(tr("Measurements"))
        meas_layout = QVBoxLayout()
        meas_layout.setContentsMargins(4, 2, 4, 2)

        meas_row_1 = QHBoxLayout()
        self.meas_l_label = QLabel()
        self.meas_l_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
        meas_row_1.addWidget(self.meas_l_label)

        self.meas_r_label = QLabel()
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

        # Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("bottom", tr("Time"), units="s")
        self.plot_widget.setLabel("left", tr("Divisions"), units="div")
        self.plot_widget.setYRange(self.VIEW_Y_MIN, self.VIEW_Y_MAX, padding=0)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        bottom_axis = self.plot_widget.getPlotItem().getAxis("bottom")
        bottom_axis.setStyle(showValues=self.module.show_x_axis)
        if not self.module.show_x_axis:
            bottom_axis.setLabel("")
            bottom_axis.setHeight(0)

        self.curve_l = self.plot_widget.plot(pen=pg.mkPen("#00ff00", width=2), name=tr("Left"))
        self.curve_r = self.plot_widget.plot(pen=pg.mkPen("#ff5555", width=2), name=tr("Right"))

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

        # Direct Manipulation: Dragable Trigger Level Line
        self.trig_line = pg.InfiniteLine(
            angle=0,
            movable=True,
            pen=pg.mkPen("#e0af00", width=1.5, style=Qt.PenStyle.DashLine),
            label=tr("Trig: {value:.2f} div"),
            labelOpts={"position": 0.9, "color": "#e0af00"},
        )
        self.trig_line.sigPositionChanged.connect(self.on_trig_line_dragged)
        self.plot_widget.addItem(self.trig_line)
        self.trig_line.setPos(0.0)

        # Persistence Images
        self.persistence_img = pg.ImageItem()
        self.plot_widget.addItem(self.persistence_img)
        self.persistence_img.setVisible(False)
        self.persistence_img.setZValue(0)

        left_layout.addWidget(self.plot_widget)

        self._update_badges()
        self._update_calibration_status()
        return display_widget

    def _setup_right_panel(self):
        right_widget = QWidget()
        right_widget.setFixedWidth(240)
        right_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        btn_header = QHBoxLayout()
        self.toggle_btn = QPushButton(tr("Start"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle)

        self.btn_auto_scale = QPushButton(tr("Auto Scale"))
        self.btn_auto_scale.setToolTip(tr("Automatically optimize timebase, vertical scale, and trigger"))
        self.btn_auto_scale.clicked.connect(self.on_auto_scale)

        btn_header.addWidget(self.toggle_btn, stretch=1)
        btn_header.addWidget(self.btn_auto_scale, stretch=1)
        right_layout.addLayout(btn_header)

        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())
        else:
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_LIGHT)

        tabs = QTabWidget()
        right_layout.addWidget(tabs)

        tab_controls = QWidget()
        tab_tools_filter = QWidget()

        tabs.addTab(tab_controls, tr("General"))
        tabs.addTab(tab_tools_filter, tr("Tools"))

        controls_layout = QVBoxLayout(tab_controls)
        controls_layout.setContentsMargins(4, 6, 4, 6)
        tools_tab_layout = QVBoxLayout(tab_tools_filter)
        tools_tab_layout.setContentsMargins(4, 6, 4, 6)

        gen_group = QGroupBox(tr("Timebase"))
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
        hbox_tb = QHBoxLayout()
        hbox_tb.addWidget(QLabel(tr("Time/Div:")))
        self.timebase_combo = QComboBox()
        for label, _ in self.module.TIME_DIV_OPTIONS:
            self.timebase_combo.addItem(label)
        self.timebase_combo.setCurrentText("1 ms")
        self.timebase_combo.currentTextChanged.connect(self.on_timebase_changed)
        hbox_tb.addWidget(self.timebase_combo)
        gen_layout.addLayout(hbox_tb)

        self.timebase_slider = QSlider(Qt.Orientation.Horizontal)
        self.timebase_slider.setRange(0, len(self.module.TIME_DIV_OPTIONS) - 1)
        self.timebase_slider.valueChanged.connect(self.on_timebase_slider_changed)
        idx_1ms = [lbl for lbl, _ in self.module.TIME_DIV_OPTIONS].index("1 ms")
        self.timebase_slider.setValue(idx_1ms)
        gen_layout.addWidget(self.timebase_slider)

        self.chk_show_x_axis = QCheckBox(tr("Show X-Axis Label"))
        self.chk_show_x_axis.setChecked(self.module.show_x_axis)
        self.chk_show_x_axis.toggled.connect(self.on_show_x_axis_toggled)
        gen_layout.addWidget(self.chk_show_x_axis)

    def _get_active_vdiv_options(self):
        is_calibrated, _, _ = self.module.get_amplitude_display_state()
        return self.module.VDIV_OPTIONS_CALIBRATED if is_calibrated else self.module.VDIV_OPTIONS_UNCALIBRATED

    def _setup_vertical_controls(self, vert_layout):
        hbox_ch = QHBoxLayout()
        self.chk_left = QCheckBox(tr("Left Ch"))
        self.chk_left.setChecked(True)
        self.chk_left.toggled.connect(self.on_ch_left_toggled)
        hbox_ch.addWidget(self.chk_left)

        self.chk_right = QCheckBox(tr("Right Ch"))
        self.chk_right.setChecked(True)
        self.chk_right.toggled.connect(self.on_ch_right_toggled)
        hbox_ch.addWidget(self.chk_right)
        vert_layout.addLayout(hbox_ch)

        # Left Scale
        hbox_scale_l = QHBoxLayout()
        self.lbl_scale_l = QLabel(tr("Left") + " " + tr("Scale:"))
        hbox_scale_l.addWidget(self.lbl_scale_l)
        self.vscale_combo_l = QComboBox()
        self.vscale_combo_l.currentTextChanged.connect(self.on_vscale_left_changed)
        hbox_scale_l.addWidget(self.vscale_combo_l)
        vert_layout.addLayout(hbox_scale_l)

        self.vscale_slider_l = QSlider(Qt.Orientation.Horizontal)
        self.vscale_slider_l.valueChanged.connect(self.on_vscale_left_slider_changed)
        vert_layout.addWidget(self.vscale_slider_l)

        # Right Scale
        hbox_scale_r = QHBoxLayout()
        self.lbl_scale_r = QLabel(tr("Right") + " " + tr("Scale:"))
        hbox_scale_r.addWidget(self.lbl_scale_r)
        self.vscale_combo_r = QComboBox()
        self.vscale_combo_r.currentTextChanged.connect(self.on_vscale_right_changed)
        hbox_scale_r.addWidget(self.vscale_combo_r)
        vert_layout.addLayout(hbox_scale_r)

        self.vscale_slider_r = QSlider(Qt.Orientation.Horizontal)
        self.vscale_slider_r.valueChanged.connect(self.on_vscale_right_slider_changed)
        vert_layout.addWidget(self.vscale_slider_r)

        self._refresh_scale_combos()

    def _refresh_scale_combos(self):
        options = self._get_active_vdiv_options()
        labels = [lbl for lbl, _ in options]

        self.vscale_combo_l.blockSignals(True)
        self.vscale_combo_r.blockSignals(True)
        self.vscale_slider_l.blockSignals(True)
        self.vscale_slider_r.blockSignals(True)

        self.vscale_combo_l.clear()
        self.vscale_combo_r.clear()
        self.vscale_combo_l.addItems(labels)
        self.vscale_combo_r.addItems(labels)

        self.vscale_slider_l.setRange(0, len(options) - 1)
        self.vscale_slider_r.setRange(0, len(options) - 1)

        self._select_closest_vdiv(self.module.vdiv_left, self.vscale_combo_l, self.vscale_slider_l, options)
        self._select_closest_vdiv(self.module.vdiv_right, self.vscale_combo_r, self.vscale_slider_r, options)

        self.vscale_combo_l.blockSignals(False)
        self.vscale_combo_r.blockSignals(False)
        self.vscale_slider_l.blockSignals(False)
        self.vscale_slider_r.blockSignals(False)

    def _select_closest_vdiv(self, current_val, combo, slider, options):
        vals = [v for _, v in options]
        closest_idx = int(np.argmin([abs(v - current_val) for v in vals]))
        combo.setCurrentIndex(closest_idx)
        slider.setValue(closest_idx)

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
        self.lbl_trig_lvl = QLabel(tr("Level (div):"))
        hbox_lvl.addWidget(self.lbl_trig_lvl)
        self.trig_level_spin = QDoubleSpinBox()
        self.trig_level_spin.setRange(-4.0, 4.0)
        self.trig_level_spin.setSingleStep(0.1)
        self.trig_level_spin.setValue(0.0)
        self.trig_level_spin.valueChanged.connect(self.on_trig_level_changed)
        hbox_lvl.addWidget(self.trig_level_spin)
        trig_layout.addLayout(hbox_lvl)

    def _setup_tools_controls(self, tools_layout):
        vbox_math = QVBoxLayout()
        hbox_math = QHBoxLayout()
        hbox_math.addWidget(QLabel(tr("Math:")))
        self.math_combo = QComboBox()
        self.math_combo.addItems(
            [tr("Off"), tr("A + B"), tr("A - B"), tr("A * B"), tr("A / B"), tr("Derivative"), tr("Integral")]
        )
        self.math_combo.currentTextChanged.connect(self.on_math_changed)
        hbox_math.addWidget(self.math_combo)
        vbox_math.addLayout(hbox_math)

        self.btn_math_reset_scale = QPushButton(tr("Fit Scale"))
        self.btn_math_reset_scale.setToolTip(tr("Auto-fit and fix Math Y-axis scale"))
        self.btn_math_reset_scale.clicked.connect(self.on_math_reset_scale_clicked)
        vbox_math.addWidget(self.btn_math_reset_scale)

        tools_layout.addLayout(vbox_math)

        self.chk_cursors = QCheckBox(tr("Enable Cursors"))
        self.chk_cursors.toggled.connect(self.on_cursors_toggled)
        tools_layout.addWidget(self.chk_cursors)

        self.chk_wave_meas = QCheckBox(tr("Enable Waveform Measurements"))
        self.chk_wave_meas.toggled.connect(self.on_wave_meas_toggled)
        tools_layout.addWidget(self.chk_wave_meas)

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
        persist_layout.addLayout(hbox_decay)

        hbox_intensity = QHBoxLayout()
        hbox_intensity.addWidget(QLabel(tr("Intensity:")))
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(1, 100)
        self.intensity_slider.setValue(int(self.module.persistence_intensity * 100))
        self.intensity_slider.valueChanged.connect(self.on_intensity_changed)
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

        self.filter_stack.addWidget(QWidget())

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
        self.math_view = pg.ViewBox()
        self.plot_widget.plotItem.scene().addItem(self.math_view)
        self.math_view.setXLink(self.plot_widget.plotItem)

        if self.plot_widget.plotItem.getAxis("right") is not None:
            self.plot_widget.plotItem.layout.removeItem(self.plot_widget.plotItem.getAxis("right"))
        self.axis_math = pg.AxisItem("right")
        self.axis_math.linkToView(self.math_view)
        self.axis_math.setLabel(tr("Math"), color="#ffffff")
        self.plot_widget.plotItem.layout.addItem(self.axis_math, 2, 2)
        self.axis_math.hide()

        self.plot_widget.plotItem.vb.sigResized.connect(self.update_math_view_geometry)

        self.curve_math = pg.PlotCurveItem(pen=pg.mkPen("w", width=2, style=Qt.PenStyle.DotLine), name=tr("Math"))
        self.math_view.addItem(self.curve_math)

    def update_math_view_geometry(self):
        self.math_view.setGeometry(self.plot_widget.plotItem.vb.sceneBoundingRect())
        self.math_view.linkedViewChanged(self.plot_widget.plotItem.vb, self.math_view.XAxis)

    def on_toggle(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.toggle_btn.setText(tr("Stop"))
            self.clipping_warning_badge.setVisible(False)
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.toggle_btn.setText(tr("Start"))

        self._update_badges()

    def on_auto_scale(self):
        """Perform automatic scaling of timebase, vertical ranges, and trigger."""
        success = self.module.auto_scale()
        if success:
            time_div_vals = [v for _, v in self.module.TIME_DIV_OPTIONS]
            closest_tb_idx = int(np.argmin([abs(v - self.module.time_div) for v in time_div_vals]))
            self.timebase_combo.setCurrentIndex(closest_tb_idx)
            self.timebase_slider.setValue(closest_tb_idx)

            self._refresh_scale_combos()

            self.trig_source_combo.setCurrentIndex(self.module.trigger_source)
            self.trig_mode_combo.setCurrentText(tr(self.module.trigger_mode))
            self.trig_slope_combo.setCurrentText(tr(self.module.trigger_slope))
            self.trig_level_spin.setValue(0.0)
            self.trig_line.setPos(0.0)

            self.plot_widget.setXRange(0, self.module.timebase, padding=0)
            self._update_badges()

    def on_show_x_axis_toggled(self, checked):
        self.module.show_x_axis = checked
        if not self.is_compact_mode():
            bottom_axis = self.plot_widget.getPlotItem().getAxis("bottom")
            bottom_axis.setStyle(showValues=checked)
            if checked:
                bottom_axis.setLabel(tr("Time"), units="s")
                bottom_axis.setHeight(None)
            else:
                bottom_axis.setLabel("")
                bottom_axis.setHeight(0)

    def on_timebase_changed(self, text):
        options_dict = dict(self.module.TIME_DIV_OPTIONS)
        if text in options_dict:
            val = options_dict[text]
            self.module.time_div = val
            self.module.timebase = val * 10.0
            self.plot_widget.setXRange(0, self.module.timebase, padding=0)
            if self.module.persistence_mode:
                self.module.reset_persistence()

            labels = [lbl for lbl, _ in self.module.TIME_DIV_OPTIONS]
            if text in labels:
                self.timebase_slider.blockSignals(True)
                self.timebase_slider.setValue(labels.index(text))
                self.timebase_slider.blockSignals(False)

        self._update_badges()

    def on_timebase_slider_changed(self, idx):
        labels = [lbl for lbl, _ in self.module.TIME_DIV_OPTIONS]
        if 0 <= idx < len(labels):
            self.timebase_combo.setCurrentText(labels[idx])

    def on_vscale_left_changed(self, text):
        options = dict(self._get_active_vdiv_options())
        if text in options:
            self.module.vdiv_left = options[text]
            labels = [lbl for lbl, _ in self._get_active_vdiv_options()]
            if text in labels:
                self.vscale_slider_l.blockSignals(True)
                self.vscale_slider_l.setValue(labels.index(text))
                self.vscale_slider_l.blockSignals(False)
            if self.module.persistence_mode:
                self.module.reset_persistence()
        self._update_badges()

    def on_vscale_left_slider_changed(self, idx):
        labels = [lbl for lbl, _ in self._get_active_vdiv_options()]
        if 0 <= idx < len(labels):
            self.vscale_combo_l.setCurrentText(labels[idx])

    def on_vscale_right_changed(self, text):
        options = dict(self._get_active_vdiv_options())
        if text in options:
            self.module.vdiv_right = options[text]
            labels = [lbl for lbl, _ in self._get_active_vdiv_options()]
            if text in labels:
                self.vscale_slider_r.blockSignals(True)
                self.vscale_slider_r.setValue(labels.index(text))
                self.vscale_slider_r.blockSignals(False)
            if self.module.persistence_mode:
                self.module.reset_persistence()
        self._update_badges()

    def on_vscale_right_slider_changed(self, idx):
        labels = [lbl for lbl, _ in self._get_active_vdiv_options()]
        if 0 <= idx < len(labels):
            self.vscale_combo_r.setCurrentText(labels[idx])

    def on_ch_left_toggled(self, checked):
        self.module.show_left = checked
        self.curve_l.setVisible(checked and not self.module.persistence_mode)
        self._update_badges()

    def on_ch_right_toggled(self, checked):
        self.module.show_right = checked
        self.curve_r.setVisible(checked and not self.module.persistence_mode)
        self._update_badges()

    def on_trig_source_changed(self, index):
        self.module.trigger_source = index
        self._update_badges()

    def on_trig_slope_changed(self, text):
        self.module.trigger_slope = "Falling" if "Fall" in text else "Rising"
        self._update_badges()

    def on_trig_mode_changed(self, text):
        text_to_mode = {
            tr("Auto"): "Auto",
            tr("Normal"): "Normal",
            tr("Single"): "Single",
            "Auto": "Auto",
            "Normal": "Normal",
            "Single": "Single",
        }
        mode = text_to_mode.get(text, "Auto")
        self.module.trigger_mode = mode

        if mode == "Single":
            self.module.single_shot_armed = True
            self.module.single_shot_fired = False
        else:
            self.module.single_shot_armed = False
            self.module.single_shot_fired = False

        self._update_badges()

    def on_trig_level_changed(self, div_val):
        """Trigger level spinbox changed in divisions (-4.0 to +4.0 div)."""
        active_vdiv = self.module.vdiv_left if self.module.trigger_source == 0 else self.module.vdiv_right
        physical_level = div_val * active_vdiv
        self.module.trigger_level = physical_level

        if not self._updating_trigger_line:
            self._updating_trigger_line = True
            self.trig_line.setPos(div_val)
            self._updating_trigger_line = False

        self._update_badges()

    def on_trig_line_dragged(self):
        """Direct manipulation: User dragged the trigger line on the plot."""
        if not self._updating_trigger_line:
            self._updating_trigger_line = True
            div_val = float(self.trig_line.value())
            div_val = max(self.VIEW_Y_MIN, min(self.VIEW_Y_MAX, div_val))
            self.trig_level_spin.setValue(div_val)

            active_vdiv = self.module.vdiv_left if self.module.trigger_source == 0 else self.module.vdiv_right
            self.module.trigger_level = div_val * active_vdiv
            self._updating_trigger_line = False
            self._update_badges()

    def _update_badges(self):
        is_calibrated, _, unit = self.module.get_amplitude_display_state()
        scale_unit = "V/div" if is_calibrated else "FS/div"

        l_status = tr("ON") if self.module.show_left else tr("OFF")
        self.badge_l_label.setText(
            f"CH1: {format_si(self.module.vdiv_left, scale_unit, sig_figs=3)} [{l_status}]"
        )
        self.badge_l_label.setStyleSheet(
            "QLabel { color: #00ff00; font-weight: bold; background: #16241a; padding: 3px 6px; border-radius: 3px; border: 1px solid #00aa00; }"
            if self.module.show_left
            else "QLabel { color: #555555; background: #111111; padding: 3px 6px; border-radius: 3px; border: 1px solid #333333; }"
        )

        r_status = tr("ON") if self.module.show_right else tr("OFF")
        self.badge_r_label.setText(
            f"CH2: {format_si(self.module.vdiv_right, scale_unit, sig_figs=3)} [{r_status}]"
        )
        self.badge_r_label.setStyleSheet(
            "QLabel { color: #ff5555; font-weight: bold; background: #2b1818; padding: 3px 6px; border-radius: 3px; border: 1px solid #aa0000; }"
            if self.module.show_right
            else "QLabel { color: #555555; background: #111111; padding: 3px 6px; border-radius: 3px; border: 1px solid #333333; }"
        )

        slope_sym = "↑" if self.module.trigger_slope == "Rising" else "↓"
        src_str = "CH1" if self.module.trigger_source == 0 else "CH2"
        trig_info = f"{tr(self.module.trigger_mode)} {src_str} {slope_sym}"
        tb_str = format_si(self.module.time_div, "s/div", sig_figs=3)

        self.badge_status_label.setText(f"TIME: {tb_str}  |  TRIG: {trig_info}")

    def on_math_changed(self, text):
        math_mode_map = {
            tr("Off"): "Off",
            tr("A + B"): "A + B",
            tr("A - B"): "A - B",
            tr("A * B"): "A * B",
            tr("A / B"): "A / B",
            tr("Derivative"): "Derivative",
            tr("Integral"): "Integral",
            "Off": "Off",
            "A + B": "A + B",
            "A - B": "A - B",
            "A * B": "A * B",
            "A / B": "A / B",
            "Derivative": "Derivative",
            "Integral": "Integral",
        }
        val = math_mode_map.get(text, "Off")
        self.module.math_mode = val
        if val == "Off":
            self.axis_math.hide()
            self.curve_math.clear()
        else:
            self.axis_math.show()
            self.axis_math.setLabel(tr("Math ({0})").format(text), color="#ffffff")
            self._math_autofit_pending = True

    def on_math_reset_scale_clicked(self):
        self._math_autofit_pending = True

    def on_cursors_toggled(self, checked):
        self.cursor_1.setVisible(checked)
        self.cursor_2.setVisible(checked)
        if checked:
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

        v1_str = ""
        v2_str = ""
        dv_str = ""

        if hasattr(self, "latest_data") and self.latest_data is not None:
            data = self.latest_data
            t = self.latest_t

            target_data = None
            if self.module.show_left:
                target_data = data[:, 0]
            elif self.module.show_right:
                target_data = data[:, 1]

            if target_data is not None:
                is_calibrated, amplitude_factor, _unit = self.module.get_amplitude_display_state()
                amplitude_1 = np.interp(t1, t, target_data) * amplitude_factor
                amplitude_2 = np.interp(t2, t, target_data) * amplitude_factor
                delta_amplitude = amplitude_2 - amplitude_1
                if is_calibrated:
                    v1_str = tr("V1: {0:.3f}V").format(amplitude_1)
                    v2_str = tr("V2: {0:.3f}V").format(amplitude_2)
                    dv_str = tr("dV: {0:.3f}V").format(delta_amplitude)
                else:
                    v1_str = tr("A1: {0:.3f} FS").format(amplitude_1)
                    v2_str = tr("A2: {0:.3f} FS").format(amplitude_2)
                    dv_str = tr("dA: {0:.3f} FS").format(delta_amplitude)

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
            self.filter_stack.setCurrentIndex(1)

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

    def _update_calibration_status(self):
        is_calibrated, sensitivity, _unit = self.module.get_amplitude_display_state()
        if is_calibrated:
            self.calibration_status_label.setText(
                tr("Input: Calibrated ({0:.4g} V/FS)").format(sensitivity)
            )
        else:
            self.calibration_status_label.setText(tr("Input: Uncalibrated (FS)"))

    def _set_measurement_labels(self, measurements):
        is_calibrated, _factor, _unit = self.module.get_amplitude_display_state()
        if is_calibrated:
            self.meas_l_label.setText(
                tr("L: Vrms: {0:.3f} V  Vpp: {1:.3f} V").format(
                    measurements["l_rms"], measurements["l_vpp"]
                )
            )
            self.meas_r_label.setText(
                tr("R: Vrms: {0:.3f} V  Vpp: {1:.3f} V").format(
                    measurements["r_rms"], measurements["r_vpp"]
                )
            )
        else:
            self.meas_l_label.setText(
                tr("L: RMS: {0:.3f} FS  Pk-Pk: {1:.3f} FS").format(
                    measurements["l_rms"], measurements["l_vpp"]
                )
            )
            self.meas_r_label.setText(
                tr("R: RMS: {0:.3f} FS  Pk-Pk: {1:.3f} FS").format(
                    measurements["r_rms"], measurements["r_vpp"]
                )
            )

    def update_plot(self):
        if not self.module.is_running:
            return

        self.module.process_queue()

        window_duration = self.module.timebase
        data = self.module.get_display_data(window_duration)

        is_clipped = self.module.clipping_latched_l or self.module.clipping_latched_r
        self.clipping_warning_badge.setVisible(is_clipped)

        if data is not None and len(data) > 0:
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

            l_data = data[:, 0]
            r_data = data[:, 1]

            meas = self.module.get_measurements(data)
            self._update_calibration_status()
            self._set_measurement_labels(meas)

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

            self.latest_data = data
            self.latest_t = t

            plot_t = t[::display_step]
            plot_data = data[::display_step]

            is_calibrated, factor, _ = self.module.get_amplitude_display_state()
            amp_factor = factor if is_calibrated else 1.0

            scaled_l = (plot_data[:, 0] * amp_factor) / max(1e-9, self.module.vdiv_left)
            scaled_r = (plot_data[:, 1] * amp_factor) / max(1e-9, self.module.vdiv_right)

            if self.module.persistence_mode:
                decay = self.module.persistence_decay
                intensity = self.module.persistence_intensity

                self.module.heatmap_l *= decay
                self.module.heatmap_r *= decay

                w, h = self.module.heatmap_size
                rng = [[0, window_duration], [self.VIEW_Y_MIN, self.VIEW_Y_MAX]]

                if self.module.show_left:
                    self.module._accumulate_heatmap(plot_t, scaled_l, self.module.heatmap_l, [w, h], rng, intensity)
                if self.module.show_right:
                    self.module._accumulate_heatmap(plot_t, scaled_r, self.module.heatmap_r, [w, h], rng, intensity)

                if self._rgba_buffer is None or self._rgba_buffer.shape[:2] != (w, h):
                    self._rgba_buffer = np.zeros((w, h, 4), dtype=np.ubyte)
                    self._clip_buffer = np.empty((w, h), dtype=self.module.heatmap_l.dtype)

                np.clip(self.module.heatmap_l, 0, 255, out=self._clip_buffer)
                self._rgba_buffer[..., 1] = self._clip_buffer.astype(np.ubyte)

                np.clip(self.module.heatmap_r, 0, 255, out=self._clip_buffer)
                self._rgba_buffer[..., 0] = self._clip_buffer.astype(np.ubyte)

                np.maximum(
                    self._rgba_buffer[..., 1],
                    self._rgba_buffer[..., 0],
                    out=self._rgba_buffer[..., 3],
                )

                self.persistence_img.setImage(self._rgba_buffer, autoLevels=False)
                self.persistence_img.setRect(
                    pg.QtCore.QRectF(0, self.VIEW_Y_MIN, window_duration, self.VIEW_Y_MAX - self.VIEW_Y_MIN)
                )

                self.curve_l.setVisible(False)
                self.curve_r.setVisible(False)
            else:
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

            if self.module.math_mode != "Off":
                math_data = None
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
                    with np.errstate(divide="ignore", invalid="ignore"):
                        math_data = np.divide(A, B)
                        math_data[~np.isfinite(math_data)] = 0
                elif mode == "Derivative":
                    dt = t[1] - t[0] if len(t) > 1 else 1e-6
                    if len(A) >= 5:
                        padded = np.pad(A, (2, 2), mode="edge")
                        kernel = np.ones(5) / 5.0
                        A_smooth = np.convolve(padded, kernel, mode="valid")
                    else:
                        A_smooth = A
                    math_data = np.gradient(A_smooth, dt)
                elif mode == "Integral":
                    dt = t[1] - t[0] if len(t) > 1 else 1e-6
                    A_no_dc = A - np.mean(A)
                    math_data = np.cumsum(A_no_dc) * dt - 0.5 * (A_no_dc - A_no_dc[0]) * dt
                    math_data = math_data - np.mean(math_data)

                if math_data is not None and math_data.size > 0:
                    self.curve_math.setData(plot_t, math_data[::display_step])
                    if getattr(self, "_math_autofit_pending", False):
                        self._math_autofit_pending = False
                        mn, mx = np.min(math_data), np.max(math_data)
                        if mn == mx:
                            mn -= 0.1
                            mx += 0.1
                        padding = (mx - mn) * 0.15
                        self.math_view.setYRange(mn - padding, mx + padding)
                else:
                    self.curve_math.clear()
            else:
                self.curve_math.clear()

            if self.chk_cursors.isChecked():
                self.update_cursor_info()

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
            self.toggle_btn.setStyleSheet(STYLE_TOGGLE_BTN_DARK)
            self.meas_l_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
            self.meas_r_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
            if hasattr(self, "meas_l_auto_label"):
                self.meas_l_auto_label.setStyleSheet(STYLE_LABEL_LEFT_CH_DARK)
            if hasattr(self, "meas_r_auto_label"):
                self.meas_r_auto_label.setStyleSheet(STYLE_LABEL_RIGHT_CH_DARK)
            self.cursor_info_label.setStyleSheet(STYLE_LABEL_CURSOR_DARK)
        else:
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
        layout = self.layout()
        if layout is not None:
            if compact:
                if not hasattr(self, "_orig_margins"):
                    self._orig_margins = layout.contentsMargins()
                if not hasattr(self, "_orig_spacing"):
                    self._orig_spacing = layout.spacing()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
            else:
                if hasattr(self, "_orig_margins"):
                    m = self._orig_margins
                    layout.setContentsMargins(m.left(), m.top(), m.right(), m.bottom())
                if hasattr(self, "_orig_spacing"):
                    layout.setSpacing(self._orig_spacing)

        if hasattr(self, "right_widget"):
            is_split = self.right_widget.parent() is not self
            if not is_split:
                self.right_widget.setHidden(compact)
        if hasattr(self, "badge_group"):
            self.badge_group.setHidden(compact)
        if hasattr(self, "meas_group"):
            self.meas_group.setHidden(compact)
        if hasattr(self, "cursor_info_label"):
            self.cursor_info_label.setHidden(compact)

        if hasattr(self, "plot_widget"):
            bottom_axis = self.plot_widget.getPlotItem().getAxis("bottom")
            left_axis = self.plot_widget.getPlotItem().getAxis("left")
            plot_item_layout = self.plot_widget.getPlotItem().layout
            if compact:
                if not hasattr(self, "_orig_plot_margins"):
                    self._orig_plot_margins = plot_item_layout.getContentsMargins()
                self.plot_widget.setFrameShape(QFrame.Shape.NoFrame)
                self.plot_widget.setStyleSheet("border: none;")
                plot_item_layout.setContentsMargins(0, 0, 0, 0)
                bottom_axis.setStyle(showValues=False)
                bottom_axis.setLabel("")
                bottom_axis.setHeight(0)
                left_axis.setStyle(showValues=False)
                left_axis.setLabel("")
                left_axis.setWidth(0)
            else:
                self.plot_widget.setFrameShape(QFrame.Shape.StyledPanel)
                self.plot_widget.setStyleSheet("")
                if hasattr(self, "_orig_plot_margins"):
                    plot_item_layout.setContentsMargins(*self._orig_plot_margins)
                show = getattr(self.module, "show_x_axis", False)
                bottom_axis.setStyle(showValues=show)
                if show:
                    bottom_axis.setLabel(tr("Time"), units="s")
                    bottom_axis.setHeight(None)
                else:
                    bottom_axis.setLabel("")
                    bottom_axis.setHeight(0)
                left_axis.setStyle(showValues=True)
                left_axis.setLabel(tr("Divisions"), units="div")
                left_axis.setWidth(None)

    def get_comparable_data(self) -> List[ComparisonTrace]:
        if self.last_display_data is None or self.last_display_time is None:
            return []

        import uuid
        from datetime import datetime

        data = self.last_display_data
        t = self.last_display_time
        is_calibrated, input_sensitivity, _unit = self.module.get_amplitude_display_state()
        timestamp = datetime.now().isoformat()
        traces = []

        if self.module.show_left:
            trace_id = str(uuid.uuid4())
            trace_name = f"{tr('Oscilloscope')} - L ({datetime.now().strftime('%H:%M:%S')})"
            x_axis = AxisMetadata(dimension="time", base_unit="s", display_unit="s", is_log=False)

            if is_calibrated:
                y_axis = AxisMetadata(dimension="voltage", base_unit="V", display_unit="V", is_log=False)
                y_data = data[:, 0] * input_sensitivity
                ref_lvl = "absolute"
            else:
                y_axis = AxisMetadata(dimension="voltage", base_unit="FS", display_unit="FS", is_log=False)
                y_data = data[:, 0]
                ref_lvl = "relative"

            trace_l = ComparisonTrace(
                id=trace_id,
                name=trace_name,
                source_module="Oscilloscope",
                timestamp=timestamp,
                plot_type="time_series",
                x_axis=x_axis,
                y_axis=y_axis,
                x_data=t,
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

        if self.module.show_right:
            trace_id = str(uuid.uuid4())
            trace_name = f"{tr('Oscilloscope')} - R ({datetime.now().strftime('%H:%M:%S')})"
            x_axis = AxisMetadata(dimension="time", base_unit="s", display_unit="s", is_log=False)

            if is_calibrated:
                y_axis = AxisMetadata(dimension="voltage", base_unit="V", display_unit="V", is_log=False)
                y_data = data[:, 1] * input_sensitivity
                ref_lvl = "absolute"
            else:
                y_axis = AxisMetadata(dimension="voltage", base_unit="FS", display_unit="FS", is_log=False)
                y_data = data[:, 1]
                ref_lvl = "relative"

            trace_r = ComparisonTrace(
                id=trace_id,
                name=trace_name,
                source_module="Oscilloscope",
                timestamp=timestamp,
                plot_type="time_series",
                x_axis=x_axis,
                y_axis=y_axis,
                x_data=t,
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
