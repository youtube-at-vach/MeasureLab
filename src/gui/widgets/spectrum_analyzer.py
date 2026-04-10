import logging
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

from src.core.analysis import get_cached_window
from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager, get_dpss_windows
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


logger = logging.getLogger(__name__)


class SpectrumAnalyzer(MeasurementModule):
    # Threshold for switching to "Snapshot / Slow" mode
    LARGE_BUFFER_THRESHOLD = 500000

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

        # State
        self._avg_magnitude = None
        self._avg_cross_spectrum = None  # Complex average for Cross Spectrum
        self._peak_magnitude = None
        self._avg_weighted_power = None
        self.overall_rms = 0.0

        # Cache for octal smoothing bands
        # Key: (len(freqs), freqs[-1], fraction)
        # Value: (smoothed_freqs, band_indices_list)
        self._smoothing_cache = {}

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
        self.buffer_size = size
        self.input_data = np.zeros((self.buffer_size, 2))
        self.write_head = 0
        self._avg_magnitude = None
        self._avg_cross_spectrum = None
        self._peak_magnitude = None
        self._avg_weighted_power = None
        self._smoothing_cache = {}

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self._avg_magnitude = None
        self._avg_cross_spectrum = None
        self._peak_magnitude = None
        self._avg_weighted_power = None
        self.overall_rms = 0.0
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
                logger.debug(status)

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
        while not self.audio_queue.empty():
            try:
                new_data = self.audio_queue.get_nowait()
            except queue.Empty:
                break

            if self.buffer_size >= self.LARGE_BUFFER_THRESHOLD:
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

    def get_latest_data(self):
        """
        Retrieve the latest data from the ring buffer.
        Handles both "Snapshot" and "Rolling" modes.
        Returns None if not enough data (Snapshot mode).
        """
        if self.buffer_size >= self.LARGE_BUFFER_THRESHOLD:
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
            # Unroll ring buffer for display/analysis
            # Capture write_head locally to avoid race condition with audio thread changing it
            idx = self.write_head
            if idx == 0:
                data = self.input_data.copy()
            else:
                data = np.concatenate(
                    (self.input_data[idx:], self.input_data[:idx]),
                    axis=0,
                )
            return data

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False

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
            # A-weighting
            # RA(f) = (12194^2 * f^4) / ((f^2 + 20.6^2) * sqrt((f^2 + 107.7^2)(f^2 + 737.9^2)) * (f^2 + 12194^2))
            # Gain = 20*log10(RA(f)) + 2.00

            const = 12194**2 * f**4
            denom = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2)
            R_A = const / denom
            gain = 20 * np.log10(R_A) + 2.00
            return gain

        elif weighting_type == "C":
            # C-weighting
            # RC(f) = (12194^2 * f^2) / ((f^2 + 20.6^2) * (f^2 + 12194^2))
            # Gain = 20*log10(RC(f)) + 0.06

            const = 12194**2 * f2
            denom = (f2 + 20.6**2) * (f2 + 12194**2)
            R_C = const / denom
            gain = 20 * np.log10(R_C) + 0.06
            return gain

        return np.zeros_like(freqs)

    def apply_octave_smoothing(self, freqs, magnitude, fraction):
        """
        Apply fractional octave smoothing to the spectrum.
        fraction: 1 for 1/1 octave, 3 for 1/3 octave, etc.
        """
        if fraction is None:
            return freqs, magnitude

        # Check cache
        cache_key = (len(freqs), float(freqs[-1]), fraction)
        cached_data = self._smoothing_cache.get(cache_key)

        if cached_data is None:
            # --- Pre-calculate bands and indices (Slow Path) ---
            f_min = 20
            f_max = freqs[-1]

            smoothed_freqs_list = []
            band_indices = []  # List of (start_idx, end_idx)

            current_f = f_min
            factor = 2 ** (1 / (2 * fraction))
            step_factor = 2 ** (1 / fraction)

            # Pre-calculate band edges to vectorize searchsorted?
            # Doing searchsorted inside loop is O(N_bands * log(N_bins))
            # N_bands is small (~30-100), N_bins is large (~4096-1M).
            # Vectorization is better but loop is acceptable for pre-calc.

            centers = []
            bounds = []

            while current_f < f_max:
                centers.append(current_f)
                bounds.append(current_f / factor)
                bounds.append(current_f * factor)
                current_f *= step_factor

            indices = np.searchsorted(freqs, bounds, side="left")

            idx = 0
            for c in centers:
                idx_start = indices[idx]
                idx_end = indices[idx + 1]
                if idx_end > idx_start:
                    smoothed_freqs_list.append(c)
                    band_indices.append((idx_start, idx_end))
                idx += 2

            smoothed_freqs = np.array(smoothed_freqs_list)
            cached_data = (smoothed_freqs, band_indices)
            self._smoothing_cache[cache_key] = cached_data

        # --- Fast Path ---
        smoothed_freqs, band_indices = cached_data

        if len(band_indices) == 0:
            return np.array([]), np.array([])

        # Convert entire magnitude to linear once
        # Magnitude is in dB (20*log10(linear))
        # linear = 10^(mag/20)
        linear_spectrum = 10 ** (magnitude / 20.0)

        smoothed_mags_list = []

        # Iterate over pre-calculated indices
        # This is fast because we just slice and mean
        for start, end in band_indices:
            # Handle Dual Channel (N, 2) vs Single (N,)
            if linear_spectrum.ndim == 2:
                # Average over frequency bins (axis 0), keeping channels
                avg_linear = np.mean(linear_spectrum[start:end], axis=0)
            else:
                avg_linear = np.mean(linear_spectrum[start:end])

            smoothed_mags_list.append(avg_linear)

        smoothed_mags_linear = np.array(smoothed_mags_list)
        smoothed_mags_db = 20 * np.log10(smoothed_mags_linear + 1e-12)

        return smoothed_freqs, smoothed_mags_db

    def _compute_multitaper(self, data, freqs, sample_rate):
        """Helper to calculate spectrum using multitaper method."""
        windows = get_dpss_windows(len(data))  # (K, N)
        K = windows.shape[0]

        rms_power_spectrum = None
        energy_norm_factor = 1.0
        magnitude = None

        if self.analysis_mode == "Spectrum" or self.analysis_mode == "PSD":
            # Calculate PSD for each channel and each window
            psd_accum_0 = np.zeros(len(freqs))
            psd_accum_1 = np.zeros(len(freqs))

            d0 = data[:, 0]
            d1 = data[:, 1]

            for k in range(K):
                w = windows[k]
                fft_0 = fft_manager.rfft(d0 * w)
                psd_accum_0 += fft_0.real * fft_0.real
                psd_accum_0 += fft_0.imag * fft_0.imag

                fft_1 = fft_manager.rfft(d1 * w)
                psd_accum_1 += fft_1.real * fft_1.real
                psd_accum_1 += fft_1.imag * fft_1.imag

            psd_0 = psd_accum_0 / K
            psd_1 = psd_accum_1 / K

            # Apply Channel Selection
            if self.channel_mode == "Left":
                psd_target, psd_second = psd_0, None
            elif self.channel_mode == "Right":
                psd_target, psd_second = psd_1, None
            elif self.channel_mode == "Dual":
                psd_target, psd_second = psd_0, psd_1
            else:  # Average or default
                psd_target, psd_second = (psd_0 + psd_1) / 2, None

            # Capture raw power spectrum for Overall RMS
            if psd_second is not None:
                rms_power_spectrum = np.column_stack((psd_target, psd_second))
            else:
                rms_power_spectrum = psd_target

            # Energy normalization for Multitaper (sum(w^2)=1)
            energy_norm_factor = 1.0 / len(data)

            # Convert to Magnitude (Linear)
            if self.analysis_mode == "PSD":
                norm_factor_sq = 2 / sample_rate
            else:
                norm_factor_sq = 1 / len(data)

            magnitudes = [np.sqrt(psd_target * norm_factor_sq)]
            if psd_second is not None:
                magnitudes.append(np.sqrt(psd_second * norm_factor_sq))

            mag_linear = magnitudes[0] if len(magnitudes) == 1 else np.column_stack(magnitudes)

            # Peak -> RMS conversion if Physical Units or SPL
            if self.analysis_mode == "Spectrum" and self.display_unit in ["dBV", "dB SPL"]:
                mag_linear /= np.sqrt(2)

            # Temporal Averaging
            if self._avg_magnitude is None or self._avg_magnitude.shape != mag_linear.shape:
                self._avg_magnitude = mag_linear
            else:
                alpha = self.averaging
                self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_linear

            magnitude = 20 * np.log10(self._avg_magnitude + 1e-12)

        elif self.analysis_mode == "Cross Spectrum":
            cs_accum = np.zeros(len(freqs), dtype=complex)

            for k in range(K):
                w = windows[k]
                fft_0 = fft_manager.rfft(data[:, 0] * w)
                fft_1 = fft_manager.rfft(data[:, 1] * w)
                cs_accum += fft_0 * np.conj(fft_1)

            cs_avg = cs_accum / K

            # Complex Temporal Averaging
            if self._avg_cross_spectrum is None or self._avg_cross_spectrum.shape != cs_avg.shape:
                self._avg_cross_spectrum = cs_avg
            else:
                alpha = self.averaging
                self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * cs_avg

            mag_linear = np.sqrt(np.abs(self._avg_cross_spectrum)) / np.sqrt(len(data))

            if self.display_unit in ["dBV", "dB SPL"]:
                mag_linear /= np.sqrt(2)

            magnitude = 20 * np.log10(mag_linear + 1e-12)

        # Apply API/SPL adjustments
        if self.display_unit == "dBV":
            magnitude += self.audio_engine.calibration.get_input_offset_db()
        elif self.display_unit == "dB SPL":
            spl_offset = self.audio_engine.calibration.get_spl_offset_db()
            if spl_offset is not None:
                magnitude += spl_offset

        return magnitude, rms_power_spectrum, energy_norm_factor

    def _compute_standard(self, data, sample_rate):
        """Helper to calculate spectrum using standard windowing method."""
        window_name = {"rect": "boxcar", "hanning": "hann"}.get(self.window_type, self.window_type)
        window = get_cached_window(window_name, len(data), fftbins=False)
        window_correction = 1.0 / np.mean(window)
        windowed_data = data * window[:, np.newaxis]

        # FFT
        fft_data = np.column_stack((fft_manager.rfft(windowed_data[:, 0]), fft_manager.rfft(windowed_data[:, 1])))

        norm_factor = (2.0 / len(data)) * window_correction
        S2 = np.sum(window**2)
        energy_norm_factor = 1.0 / (len(data) * S2)

        raw_sq = np.abs(fft_data) ** 2
        if self.channel_mode == "Left":
            rms_power_spectrum = raw_sq[:, 0]
        elif self.channel_mode == "Right":
            rms_power_spectrum = raw_sq[:, 1]
        elif self.channel_mode == "Dual":
            rms_power_spectrum = raw_sq
        else:
            rms_power_spectrum = np.mean(raw_sq, axis=1)

        magnitude = None

        if self.analysis_mode == "Spectrum":
            mag_stereo = np.abs(fft_data)

            if self.channel_mode == "Left":
                mag_mono, mag_second = mag_stereo[:, 0], None
            elif self.channel_mode == "Right":
                mag_mono, mag_second = mag_stereo[:, 1], None
            elif self.channel_mode == "Dual":
                mag_mono, mag_second = mag_stereo[:, 0], mag_stereo[:, 1]
            else:
                mag_mono, mag_second = np.mean(mag_stereo, axis=1), None

            mag_mono = mag_mono * norm_factor
            if mag_second is not None:
                mag_second = mag_second * norm_factor

            if self.display_unit in ["dBV", "dB SPL"]:
                mag_mono /= np.sqrt(2)
                if mag_second is not None:
                    mag_second /= np.sqrt(2)

            current_mag = np.column_stack((mag_mono, mag_second)) if mag_second is not None else mag_mono

            if self._avg_magnitude is None or self._avg_magnitude.shape != current_mag.shape:
                self._avg_magnitude = current_mag
            else:
                alpha = self.averaging
                self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * current_mag

            magnitude = 20 * np.log10(self._avg_magnitude + 1e-12)

        elif self.analysis_mode == "PSD":
            sum_w = np.sum(window)
            psd_factor = sum_w / np.sqrt(2 * sample_rate * S2)

            mag_stereo = np.abs(fft_data) * norm_factor * psd_factor

            if self.channel_mode == "Left":
                mag_mono = mag_stereo[:, 0]
            elif self.channel_mode == "Right":
                mag_mono = mag_stereo[:, 1]
            elif self.channel_mode == "Dual":
                mag_mono = mag_stereo
            else:
                mag_mono = np.sqrt(np.mean(mag_stereo**2, axis=1))

            if self._avg_magnitude is None or self._avg_magnitude.shape != mag_mono.shape:
                self._avg_magnitude = mag_mono
            else:
                alpha = self.averaging
                self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_mono

            magnitude = 20 * np.log10(self._avg_magnitude + 1e-12)

        elif self.analysis_mode == "Cross Spectrum":
            Sxy = fft_data[:, 0] * np.conj(fft_data[:, 1]) * (norm_factor**2)

            if self._avg_cross_spectrum is None or len(self._avg_cross_spectrum) != len(Sxy):
                self._avg_cross_spectrum = Sxy
            else:
                alpha = self.averaging
                self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * Sxy

            magnitude_linear = np.sqrt(np.abs(self._avg_cross_spectrum))
            if self.display_unit in ["dBV", "dB SPL"]:
                magnitude_linear /= np.sqrt(2)

            magnitude = 20 * np.log10(magnitude_linear + 1e-12)

        # Apply API/SPL adjustments
        if self.display_unit == "dBV":
            magnitude += self.audio_engine.calibration.get_input_offset_db()
        elif self.display_unit == "dB SPL":
            spl_offset = self.audio_engine.calibration.get_spl_offset_db()
            if spl_offset is not None:
                magnitude += spl_offset

        return magnitude, rms_power_spectrum, energy_norm_factor

    def _calculate_overall_rms(self, freqs, rms_power_spectrum, energy_norm_factor, weighting_db):
        """Helper to calculate the overall weighted RMS."""
        overall_weighted_db = -120.0
        if rms_power_spectrum is not None:
            w_lin_sq = 10 ** (weighting_db / 10.0)
            p_weighted = rms_power_spectrum * (
                w_lin_sq[:, np.newaxis] if rms_power_spectrum.ndim == 2 and w_lin_sq.ndim == 1 else w_lin_sq
            )
            mask = (freqs >= 20) & (freqs <= 20000)

            if np.any(mask):
                sum_p = 2 * np.sum(p_weighted[mask])
                current_frame_power = sum_p * energy_norm_factor

                if self._avg_weighted_power is None:
                    self._avg_weighted_power = current_frame_power
                else:
                    alpha = self.averaging
                    if np.isscalar(current_frame_power) and np.isscalar(self._avg_weighted_power):
                        self._avg_weighted_power = alpha * self._avg_weighted_power + (1 - alpha) * current_frame_power
                    else:
                        self._avg_weighted_power = current_frame_power

                overall_rms_linear = np.sqrt(self._avg_weighted_power)
                overall_weighted_db = 20 * np.log10(overall_rms_linear + 1e-12)

                if self.display_unit == "dBV":
                    overall_weighted_db += self.audio_engine.calibration.get_input_offset_db()
                elif self.display_unit == "dB SPL":
                    spl_offset = self.audio_engine.calibration.get_spl_offset_db()
                    if spl_offset is not None:
                        overall_weighted_db += spl_offset

        return overall_weighted_db

    def compute_spectrum(self):
        """
        Compute the spectrum from the latest data.
        Returns a dictionary with results.
        """
        data = self.get_latest_data()
        if data is None:
            return None

        sample_rate = self.audio_engine.sample_rate
        freqs = fft_manager.rfftfreq(len(data), 1 / sample_rate)
        weighting_db = self.compute_weighting(freqs, self.weighting)

        if self.multitaper_enabled:
            magnitude, rms_power_spectrum, energy_norm_factor = self._compute_multitaper(data, freqs, sample_rate)
        else:
            magnitude, rms_power_spectrum, energy_norm_factor = self._compute_standard(data, sample_rate)

        # Apply Weighting to Magnitude array
        if magnitude.ndim == 2 and weighting_db.ndim == 1:
            magnitude += weighting_db[:, np.newaxis]
        else:
            magnitude += weighting_db

        overall_weighted_db = self._calculate_overall_rms(freqs, rms_power_spectrum, energy_norm_factor, weighting_db)

        # Peak Hold
        if self.peak_hold:
            if self._peak_magnitude is None or len(self._peak_magnitude) != len(magnitude):
                self._peak_magnitude = magnitude
            else:
                self._peak_magnitude = np.maximum(self._peak_magnitude, magnitude)

        return {
            "freqs": freqs,
            "magnitude": magnitude,
            "overall_weighted_db": overall_weighted_db,
            "peak_magnitude": self._peak_magnitude,
        }


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
            # Fallback for "hanning" vs "hann" if needed, though get_available_windows uses "hann"
            # SpectrumAnalyzer init uses "hanning", let's standardise on what's in the list
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
        )  # For Dual mode (Left=Green, Right=Red usually, but let's stick to standard)
        # Let's use: Main (Yellow) for single/avg.
        # For Dual: Left (Green), Right (Red).
        # So we might need to change pen colors dynamically.

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
        # Reset averages when mode changes
        self.module._avg_magnitude = None
        self.module._avg_cross_spectrum = None
        self.module._peak_magnitude = None
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
        self.module._avg_magnitude = None  # Reset average
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
        # Reset peak when weighting changes
        self.module._peak_magnitude = None
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
            self.module._peak_magnitude = None
            self.peak_curve.setData([], [])

    def on_clear_peak(self):
        self.module._peak_magnitude = None
        self.peak_curve.setData([], [])

    def on_unit_changed(self, val):
        self.module.display_unit = val
        unit = val
        if self.module.analysis_mode == "PSD":
            unit += "/√Hz"
        self.plot_widget.setLabel("left", "Magnitude", units=unit)
        # Reset peak to avoid mixing units
        self.module._peak_magnitude = None
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
        overall_weighted_db = results["overall_weighted_db"]
        peak_magnitude = results["peak_magnitude"]

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

        # Smoothing
        fraction_map = {"1/1 Octave": 1, "1/3 Octave": 3, "1/6 Octave": 6, "1/12 Octave": 12, "1/24 Octave": 24}
        fraction = fraction_map.get(self.module.octave_smoothing)

        if fraction:
            plot_freqs, plot_mags = self.module.apply_octave_smoothing(freqs, magnitude, fraction)
            if self.module.peak_hold and peak_magnitude is not None:
                _, peak_mags = self.module.apply_octave_smoothing(freqs, peak_magnitude, fraction)
            else:
                peak_mags = None
        else:
            plot_freqs = freqs[1:]
            plot_mags = magnitude[1:]
            if self.module.peak_hold and peak_magnitude is not None:
                peak_mags = peak_magnitude[1:]
            else:
                peak_mags = None

        # Update curves
        # When setLogMode(x=True) is active, we must pass LINEAR x values to setData.
        # pyqtgraph handles the log conversion.
        # We should exclude 0Hz to avoid log(0) issues inside pyqtgraph.

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
                plot_mags = plot_mags[:, 0]  # Should not happen if logic above is correct for non-Dual

            self.plot_curve.setData(plot_freqs_linear, plot_mags, pen="y")
            self.plot_curve_2.setData([], [])

        if peak_mags is not None:
            # Peak hold usually just max of whatever we are displaying.
            # If Dual, peak hold might be complex. Let's just show peak of primary (Left) or max of both?
            # For simplicity, if Dual, let's just not show Peak Hold or show it for Left.
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
