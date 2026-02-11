import queue
import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
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
from scipy.signal.windows import dpss

from src.core.analysis import get_cached_window
from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule

class SpectrumResult:
    def __init__(self, plot_freqs, plot_mags, peak_mags, overall_db, unit_display, channel_mode):
        self.plot_freqs = plot_freqs
        self.plot_mags = plot_mags
        self.peak_mags = peak_mags
        self.overall_db = overall_db
        self.unit_display = unit_display
        self.channel_mode = channel_mode

class SpectrumAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 4096
        # Store stereo data: (frames, 2)
        self.input_data = np.zeros((self.buffer_size, 2))
        self.write_head = 0
        self.audio_queue = queue.Queue()
        self.lock = threading.Lock()

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

        # Flags for worker state management
        self.reset_averaging_request = False
        self.clear_peak_request = False

        self.callback_id = None

    @property
    def name(self) -> str:
        return "Spectrum Analyzer"

    @property
    def description(self) -> str:
        return "Real-time frequency spectrum analysis."

    def get_widget(self):
        return SpectrumAnalyzerWidget(self)

    def set_buffer_size(self, size):
        with self.lock:
            self.buffer_size = size
            self.input_data = np.zeros((self.buffer_size, 2))
            self.write_head = 0
        self.reset_averaging_request = True

    def start_analysis(self):
        if self.is_running:
            return

        with self.lock:
            self.is_running = True
            self.input_data = np.zeros((self.buffer_size, 2))
            self.write_head = 0

        self.reset_averaging_request = True
        self.clear_peak_request = True

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

        with self.lock:
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

    def get_data_snapshot(self):
        LARGE_BUFFER_THRESHOLD = 500000
        with self.lock:
            if self.buffer_size >= LARGE_BUFFER_THRESHOLD:
                # Snapshot Mode Logic
                if self.write_head < self.buffer_size:
                    # Buffer not full yet, wait
                    return None

                # Buffer full, take snapshot and reset
                data = self.input_data.copy()
                self.write_head = 0
                return data
            else:
                # Normal Rolling Mode
                # Unroll ring buffer for display/analysis
                idx = self.write_head
                if idx == 0:
                    return self.input_data.copy()
                else:
                    return np.concatenate(
                        (self.input_data[idx:], self.input_data[:idx]),
                        axis=0,
                    )

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            with self.lock:
                self.is_running = False

class SpectrumAnalysisWorker(QThread):
    results_ready = pyqtSignal(object)

    def __init__(self, module: SpectrumAnalyzer):
        super().__init__()
        self.module = module
        # Worker-local State
        self._avg_magnitude = None
        self._avg_cross_spectrum = None
        self._peak_magnitude = None
        self._avg_weighted_power = None

        # Multitaper cache
        self._dpss_windows = None
        self._dpss_cache_key = None

    def _get_dpss_windows(self, N, NW=3, Kmax=None):
        """
        Get DPSS windows, caching them for performance.
        """
        if Kmax is None:
            Kmax = 2 * NW - 1

        key = (N, NW, Kmax)
        if self._dpss_windows is None or self._dpss_cache_key != key:
            self._dpss_windows = dpss(N, NW, int(Kmax))
            self._dpss_cache_key = key

        return self._dpss_windows

    def compute_weighting(self, freqs, weighting_type):
        """
        Compute weighting gain in dB for given frequencies.
        """
        if weighting_type == "Z":
            return np.zeros_like(freqs)

        f = freqs.copy()
        # Avoid division by zero or log of zero issues at DC
        f[f == 0] = 1e-9

        f2 = f**2

        if weighting_type == "A":
            const = 12194**2 * f**4
            denom = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2)
            R_A = const / denom
            gain = 20 * np.log10(R_A) + 2.00
            return gain

        elif weighting_type == "C":
            const = 12194**2 * f2
            denom = (f2 + 20.6**2) * (f2 + 12194**2)
            R_C = const / denom
            gain = 20 * np.log10(R_C) + 0.06
            return gain

        return np.zeros_like(freqs)

    def apply_octave_smoothing(self, freqs, magnitude, fraction):
        """
        Apply fractional octave smoothing to the spectrum.
        """
        if fraction is None:
            return freqs, magnitude

        # Define octave bands
        # Start from a low frequency, e.g., 20Hz
        f_min = 20
        f_max = freqs[-1]

        smoothed_freqs = []
        smoothed_mags = []

        current_f = f_min
        # factor = 2^(1/(2*fraction))
        factor = 2 ** (1 / (2 * fraction))
        step_factor = 2 ** (1 / fraction)

        while current_f < f_max:
            lower = current_f / factor
            upper = current_f * factor

            idx_start = np.searchsorted(freqs, lower, side="left")
            idx_end = np.searchsorted(freqs, upper, side="left")

            if idx_end > idx_start:
                linear_mags = 10 ** (magnitude[idx_start:idx_end] / 20)
                # Use axis=0 to preserve channel dimension if present (Dual mode)
                avg_linear = np.mean(linear_mags, axis=0)
                avg_db = 20 * np.log10(avg_linear + 1e-12)

                smoothed_freqs.append(current_f)
                smoothed_mags.append(avg_db)

            current_f *= step_factor

        return np.array(smoothed_freqs), np.array(smoothed_mags)

    def process_cycle(self):
        # Check requests from UI
        if self.module.clear_peak_request:
            self._peak_magnitude = None
            self.module.clear_peak_request = False

        if self.module.reset_averaging_request:
            self._avg_magnitude = None
            self._avg_cross_spectrum = None
            self._avg_weighted_power = None
            self.module.reset_averaging_request = False

        # Process Queue
        self.module.process_queue()

        # Get Data
        data = self.module.get_data_snapshot()

        if data is None:
            return None

        # --- Analysis Logic (Moved from update_plot) ---

        # Capture params locally to ensure consistency during this frame
        sample_rate = self.module.audio_engine.sample_rate
        weighting_type = self.module.weighting
        analysis_mode = self.module.analysis_mode
        channel_mode = self.module.channel_mode
        display_unit = self.module.display_unit
        multitaper_enabled = self.module.multitaper_enabled
        averaging_val = self.module.averaging
        peak_hold_enabled = self.module.peak_hold
        octave_smoothing = self.module.octave_smoothing
        window_type = self.module.window_type

        freqs = fft_manager.rfftfreq(len(data), 1 / sample_rate)
        weighting_db = self.compute_weighting(freqs, weighting_type)

        magnitude = None
        rms_power_spectrum = None
        energy_norm_factor = 1.0

        if multitaper_enabled:
            windows = self._get_dpss_windows(len(data))
            K = windows.shape[0]

            if analysis_mode == "Spectrum" or analysis_mode == "PSD":
                psd_accum_0 = np.zeros(len(freqs))
                psd_accum_1 = np.zeros(len(freqs))

                for k in range(K):
                    w = windows[k]
                    fft_0 = fft_manager.rfft(data[:, 0] * w)
                    psd_accum_0 += np.abs(fft_0) ** 2
                    fft_1 = fft_manager.rfft(data[:, 1] * w)
                    psd_accum_1 += np.abs(fft_1) ** 2

                psd_0 = psd_accum_0 / K
                psd_1 = psd_accum_1 / K

                if channel_mode == "Left":
                    psd_target = psd_0
                    psd_second = None
                elif channel_mode == "Right":
                    psd_target = psd_1
                    psd_second = None
                elif channel_mode == "Average":
                    psd_target = (psd_0 + psd_1) / 2
                    psd_second = None
                elif channel_mode == "Dual":
                    psd_target = psd_0
                    psd_second = psd_1
                else:
                    psd_target = (psd_0 + psd_1) / 2
                    psd_second = None

                if psd_second is not None:
                    rms_power_spectrum = np.column_stack((psd_target, psd_second))
                else:
                    rms_power_spectrum = psd_target

                energy_norm_factor = 1.0 / len(data)

                if analysis_mode == "PSD":
                    norm_factor_sq = 2 / sample_rate
                else:
                    norm_factor_sq = 1 / len(data)

                magnitudes = []
                mag_target = np.sqrt(psd_target * norm_factor_sq)
                magnitudes.append(mag_target)

                if psd_second is not None:
                    mag_second = np.sqrt(psd_second * norm_factor_sq)
                    magnitudes.append(mag_second)

                if len(magnitudes) == 1:
                    mag_linear = magnitudes[0]
                else:
                    mag_linear = np.column_stack(magnitudes)

                if analysis_mode == "Spectrum" and display_unit in ["dBV", "dB SPL"]:
                    mag_linear /= np.sqrt(2)

                if self._avg_magnitude is None or self._avg_magnitude.shape != mag_linear.shape:
                    self._avg_magnitude = mag_linear
                else:
                    alpha = averaging_val
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_linear

                magnitude = 20 * np.log10(self._avg_magnitude + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    magnitude += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        magnitude += spl_offset

            elif analysis_mode == "Cross Spectrum":
                cs_accum = np.zeros(len(freqs), dtype=complex)
                for k in range(K):
                    w = windows[k]
                    fft_0 = fft_manager.rfft(data[:, 0] * w)
                    fft_1 = fft_manager.rfft(data[:, 1] * w)
                    cs_accum += fft_0 * np.conj(fft_1)

                cs_avg = cs_accum / K

                if self._avg_cross_spectrum is None or self._avg_cross_spectrum.shape != cs_avg.shape:
                    self._avg_cross_spectrum = cs_avg
                else:
                    alpha = averaging_val
                    self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * cs_avg

                avg_cs = self._avg_cross_spectrum
                mag_linear = np.sqrt(np.abs(avg_cs)) / np.sqrt(len(data))

                if display_unit in ["dBV", "dB SPL"]:
                    mag_linear /= np.sqrt(2)

                magnitude = 20 * np.log10(mag_linear + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    magnitude += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        magnitude += spl_offset

        else:
            # Standard Method
            if window_type == "rect":
                window_name = "boxcar"
            elif window_type == "hanning":
                window_name = "hann"
            else:
                window_name = window_type

            window = get_cached_window(window_name, len(data), fftbins=False)
            window_correction = 1.0 / np.mean(window)
            windowed_data = data * window[:, np.newaxis]

            f0 = fft_manager.rfft(windowed_data[:, 0])
            f1 = fft_manager.rfft(windowed_data[:, 1])
            fft_data = np.column_stack((f0, f1))

            norm_factor = (2.0 / len(data)) * window_correction
            S2 = np.sum(window**2)
            energy_norm_factor = 1.0 / (len(data) * S2)

            raw_sq = np.abs(fft_data)**2
            if channel_mode == "Left":
                rms_power_spectrum = raw_sq[:, 0]
            elif channel_mode == "Right":
                rms_power_spectrum = raw_sq[:, 1]
            elif channel_mode == "Average":
                rms_power_spectrum = np.mean(raw_sq, axis=1)
            elif channel_mode == "Dual":
                rms_power_spectrum = raw_sq
            else:
                rms_power_spectrum = np.mean(raw_sq, axis=1)

            if analysis_mode == "Spectrum":
                mag_stereo = np.abs(fft_data)
                if channel_mode == "Left":
                    mag_mono = mag_stereo[:, 0]
                    mag_second = None
                elif channel_mode == "Right":
                    mag_mono = mag_stereo[:, 1]
                    mag_second = None
                elif channel_mode == "Average":
                    mag_mono = np.mean(mag_stereo, axis=1)
                    mag_second = None
                elif channel_mode == "Dual":
                    mag_mono = mag_stereo[:, 0]
                    mag_second = mag_stereo[:, 1]
                else:
                    mag_mono = np.mean(mag_stereo, axis=1)
                    mag_second = None

                mag_mono = mag_mono * norm_factor
                if mag_second is not None:
                    mag_second = mag_second * norm_factor

                if display_unit in ["dBV", "dB SPL"]:
                    mag_mono /= np.sqrt(2)
                    if mag_second is not None:
                        mag_second /= np.sqrt(2)

                current_mag = mag_mono
                if mag_second is not None:
                    current_mag = np.column_stack((mag_mono, mag_second))

                if self._avg_magnitude is None or self._avg_magnitude.shape != current_mag.shape:
                    self._avg_magnitude = current_mag
                else:
                    alpha = averaging_val
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * current_mag

                magnitude_linear = self._avg_magnitude
                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    magnitude += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        magnitude += spl_offset

            elif analysis_mode == "PSD":
                sum_w = np.sum(window)
                sum_w2 = np.sum(window**2)
                fs = sample_rate
                psd_factor = sum_w / np.sqrt(2 * fs * sum_w2)

                mag_stereo = np.abs(fft_data)
                mag_stereo = mag_stereo * norm_factor
                mag_stereo = mag_stereo * psd_factor

                if channel_mode == "Left":
                    mag_mono = mag_stereo[:, 0]
                elif channel_mode == "Right":
                    mag_mono = mag_stereo[:, 1]
                elif channel_mode == "Average":
                    pow_stereo = mag_stereo**2
                    avg_pow = np.mean(pow_stereo, axis=1)
                    mag_mono = np.sqrt(avg_pow)
                elif channel_mode == "Dual":
                    mag_mono = mag_stereo
                else:
                    mag_mono = mag_stereo[:, 0]

                if self._avg_magnitude is None or self._avg_magnitude.shape != mag_mono.shape:
                    self._avg_magnitude = mag_mono
                else:
                    alpha = averaging_val
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_mono

                magnitude_linear = self._avg_magnitude
                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    magnitude += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        magnitude += spl_offset

            elif analysis_mode == "Cross Spectrum":
                F1 = fft_data[:, 0]
                F2 = fft_data[:, 1]
                Sxy = F1 * np.conj(F2)
                Sxy = Sxy * (norm_factor**2)

                if self._avg_cross_spectrum is None or len(self._avg_cross_spectrum) != len(Sxy):
                    self._avg_cross_spectrum = Sxy
                else:
                    alpha = averaging_val
                    self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * Sxy

                avg_Sxy = self._avg_cross_spectrum
                magnitude_linear = np.sqrt(np.abs(avg_Sxy))

                if display_unit in ["dBV", "dB SPL"]:
                    magnitude_linear /= np.sqrt(2)

                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    magnitude += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        magnitude += spl_offset

        if magnitude is not None:
            if magnitude.ndim == 2 and weighting_db.ndim == 1:
                magnitude += weighting_db[:, np.newaxis]
            else:
                magnitude += weighting_db

        # Overall RMS
        overall_weighted_db = -120.0
        if rms_power_spectrum is not None:
            w_lin_sq = 10 ** (weighting_db / 10.0)
            if rms_power_spectrum.ndim == 2 and w_lin_sq.ndim == 1:
                p_weighted = rms_power_spectrum * w_lin_sq[:, np.newaxis]
            else:
                p_weighted = rms_power_spectrum * w_lin_sq

            mask = (freqs >= 20) & (freqs <= 20000)
            if np.any(mask):
                if p_weighted.ndim == 2:
                    sum_p = 2 * np.sum(p_weighted[mask])
                else:
                    sum_p = 2 * np.sum(p_weighted[mask])

                current_frame_power = sum_p * energy_norm_factor

                if self._avg_weighted_power is None:
                    self._avg_weighted_power = current_frame_power
                else:
                    alpha = averaging_val
                    # Check safety for buffer size changes handled by reset_averaging
                    if np.isscalar(current_frame_power) and np.isscalar(self._avg_weighted_power):
                        self._avg_weighted_power = alpha * self._avg_weighted_power + (1 - alpha) * current_frame_power
                    else:
                        self._avg_weighted_power = current_frame_power

                overall_rms_linear = np.sqrt(self._avg_weighted_power)
                overall_weighted_db = 20 * np.log10(overall_rms_linear + 1e-12)

                if display_unit == "dBV":
                    offset = self.module.audio_engine.calibration.get_input_offset_db()
                    overall_weighted_db += offset
                elif display_unit == "dB SPL":
                    spl_offset = self.module.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        overall_weighted_db += spl_offset

        # Unit string
        unit_suffix = ""
        if weighting_type == "A":
            unit_suffix = "A"
        elif weighting_type == "C":
            unit_suffix = "C"
        elif weighting_type == "Z":
            unit_suffix = "Z"

        if display_unit == "dB SPL":
            unit_display = f"dB SPL({unit_suffix})"
        elif display_unit == "dBV":
            unit_display = f"dBV({unit_suffix})"
        else:
            unit_display = f"dBFS({unit_suffix})"

        # Peak Hold
        if peak_hold_enabled:
            if self._peak_magnitude is None or len(self._peak_magnitude) != len(magnitude):
                self._peak_magnitude = magnitude
            else:
                self._peak_magnitude = np.maximum(self._peak_magnitude, magnitude)

        # Smoothing
        fraction_map = {"1/1 Octave": 1, "1/3 Octave": 3, "1/6 Octave": 6, "1/12 Octave": 12, "1/24 Octave": 24}
        fraction = fraction_map.get(octave_smoothing)

        plot_freqs = None
        plot_mags = None
        peak_mags = None

        if fraction:
            plot_freqs, plot_mags = self.apply_octave_smoothing(freqs, magnitude, fraction)
            if peak_hold_enabled and self._peak_magnitude is not None:
                _, peak_mags = self.apply_octave_smoothing(freqs, self._peak_magnitude, fraction)
        else:
            plot_freqs = freqs[1:]
            plot_mags = magnitude[1:]
            if peak_hold_enabled and self._peak_magnitude is not None:
                peak_mags = self._peak_magnitude[1:]

        result = SpectrumResult(
            plot_freqs=plot_freqs,
            plot_mags=plot_mags,
            peak_mags=peak_mags,
            overall_db=overall_weighted_db,
            unit_display=unit_display,
            channel_mode=channel_mode
        )
        return result

    def run(self):
        while not self.isInterruptionRequested() and self.module.is_running:
            result = self.process_cycle()
            if result:
                self.results_ready.emit(result)
                self.msleep(30)
            else:
                self.msleep(10)

class SpectrumAnalyzerWidget(QWidget):
    def __init__(self, module: SpectrumAnalyzer):
        super().__init__()
        self.module = module
        self.worker = None
        self.init_ui()

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

        # Unit Selection
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
            if self.worker is None:
                self.worker = SpectrumAnalysisWorker(self.module)
                self.worker.results_ready.connect(self.update_display)
                self.worker.start()
            self.toggle_btn.setText(tr("Stop Analysis"))
        else:
            self.module.stop_analysis()
            if self.worker is not None:
                self.worker.requestInterruption()
                self.worker.wait()
                self.worker = None
            self.toggle_btn.setText(tr("Start Analysis"))

    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.worker.wait()
            self.worker = None
        self.module.stop_analysis()
        super().closeEvent(event)

    def on_mode_changed(self, index):
        val = self.mode_combo.itemData(index)
        if val is None:
            return
        self.module.analysis_mode = val
        self.module.reset_averaging_request = True
        self.module.clear_peak_request = True
        self.peak_curve.setData([], [])

        if val == "Cross Spectrum":
            self.channel_combo.setEnabled(False)
        else:
            self.channel_combo.setEnabled(True)

        unit = self.module.display_unit
        if val == "PSD":
            unit += "/√Hz"
        self.plot_widget.setLabel("left", "Magnitude", units=unit)

    def on_channel_changed(self, val):
        self.module.channel_mode = val
        self.module.reset_averaging_request = True
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
        self.module.clear_peak_request = True
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
        self.window_combo.setEnabled(not checked)

    def on_peak_changed(self, checked):
        self.module.peak_hold = checked
        if not checked:
            self.module.clear_peak_request = True
            self.peak_curve.setData([], [])

    def on_clear_peak(self):
        self.module.clear_peak_request = True
        self.peak_curve.setData([], [])

    def on_unit_changed(self, val):
        self.module.display_unit = val
        unit = val
        if self.module.analysis_mode == "PSD":
            unit += "/√Hz"
        self.plot_widget.setLabel("left", "Magnitude", units=unit)
        self.module.clear_peak_request = True
        self.peak_curve.setData([], [])

    def update_display(self, result: SpectrumResult):
        if result is None:
            return

        self.overall_label.setText(f"Overall: {result.overall_db:.1f} {result.unit_display}")

        plot_freqs = result.plot_freqs
        plot_mags = result.plot_mags
        peak_mags = result.peak_mags

        if plot_freqs is None or plot_mags is None:
            return

        plot_freqs_linear = plot_freqs + 1e-12

        # Handle Dual Mode Plotting
        if self.module.analysis_mode in ["Spectrum", "PSD"] and result.channel_mode == "Dual":
            if plot_mags.ndim == 2 and plot_mags.shape[1] >= 2:
                self.plot_curve.setData(plot_freqs_linear, plot_mags[:, 0], pen="g")
                self.plot_curve_2.setData(plot_freqs_linear, plot_mags[:, 1], pen="r")
            else:
                self.plot_curve.setData(plot_freqs_linear, plot_mags, pen="y")
                self.plot_curve_2.setData([], [])
        else:
            if plot_mags.ndim == 2:
                plot_mags = plot_mags[:, 0]
            self.plot_curve.setData(plot_freqs_linear, plot_mags, pen="y")
            self.plot_curve_2.setData([], [])

        if peak_mags is not None:
            if peak_mags.ndim == 2:
                peak_mags = peak_mags[:, 0]
            self.peak_curve.setData(plot_freqs_linear, peak_mags)
        else:
            self.peak_curve.setData([], [])

    def apply_theme(self, theme_name):
        # If theme_name is 'system', resolve it
        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        if theme_name == "dark":
            # Dark Theme
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #2e7d32; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
                "QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #555; border-radius: 4px; padding: 5px; }"
                "QPushButton:hover { background-color: #388e3c; }"
                "QPushButton:checked:hover { background-color: #d32f2f; }"
            )
            self.overall_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ff00;")
            self.cursor_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #00ffff;")
        else:
            # Light Theme
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #ccffcc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
                "QPushButton:checked { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; }"
                "QPushButton:hover { background-color: #bbfebb; }"
                "QPushButton:checked:hover { background-color: #ffbbbb; }"
            )
            self.overall_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #008800;")
            self.cursor_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #0000aa;")

        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())
