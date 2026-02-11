import numpy as np
from scipy.signal.windows import dpss

from src.core.analysis import get_cached_window
from src.core.fft_manager import fft_manager


class SpectrumProcessor:
    """
    Handles signal processing logic for Spectrum Analysis.
    Decouples math from UI/State management.
    """

    def __init__(self):
        # State
        self._avg_magnitude = None
        self._avg_cross_spectrum = None  # Complex average for Cross Spectrum
        self._avg_weighted_power = None
        self._peak_magnitude = None

        # Multitaper cache
        self._dpss_windows = None
        self._dpss_cache_key = None  # (N, NW, K)

    def reset(self):
        """Resets averaging and peak hold states."""
        self._avg_magnitude = None
        self._avg_cross_spectrum = None
        self._avg_weighted_power = None
        self._peak_magnitude = None
        # Reset DPSS cache as well if N changed, but usually N is passed in.
        # However, to be safe:
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
            # Generate windows
            # dpss returns (K, N) array
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
            # A-weighting
            const = 12194**2 * f**4
            denom = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194**2)
            R_A = const / denom
            gain = 20 * np.log10(R_A) + 2.00
            return gain

        elif weighting_type == "C":
            # C-weighting
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

        # Define octave bands
        # Start from a low frequency, e.g., 20Hz
        f_min = 20
        f_max = freqs[-1]

        smoothed_freqs = []
        smoothed_mags = []

        current_f = f_min
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

    def process(self, data, sample_rate, config, calibration_offsets=(0.0, 0.0)):
        """
        Process raw audio data into spectrum results.

        Args:
            data: np.array (N, channels)
            sample_rate: float
            config: dict with keys:
                - window_type (str)
                - analysis_mode (str): 'Spectrum', 'PSD', 'Cross Spectrum'
                - channel_mode (str): 'Left', 'Right', 'Average', 'Dual'
                - multitaper_enabled (bool)
                - averaging (float): 0.0 to 1.0 (approx)
                - weighting (str): 'Z', 'A', 'C'
                - display_unit (str): 'dBFS', 'dBV', 'dB SPL'
                - peak_hold (bool)
                - octave_smoothing (str): "None", "1/1 Octave", etc.
            calibration_offsets: tuple (input_offset_db, spl_offset_db)

        Returns:
            dict containing:
                - freqs
                - magnitude (dB)
                - peak_magnitude (dB or None)
                - overall_weighted_db (float)
                - smoothed_freqs (or None)
                - smoothed_magnitude (or None)
                - smoothed_peak_magnitude (or None)
        """
        # Unpack config
        window_type = config.get("window_type", "hanning")
        analysis_mode = config.get("analysis_mode", "Spectrum")
        channel_mode = config.get("channel_mode", "Average")
        multitaper_enabled = config.get("multitaper_enabled", False)
        averaging = config.get("averaging", 0.0)
        weighting = config.get("weighting", "Z")
        display_unit = config.get("display_unit", "dBFS")
        peak_hold = config.get("peak_hold", False)
        octave_smoothing = config.get("octave_smoothing", "None")

        input_offset_db, spl_offset_db = calibration_offsets

        # Frequency axis
        freqs = fft_manager.rfftfreq(len(data), 1 / sample_rate)

        # Calculate Weighting Curve
        weighting_db = self.compute_weighting(freqs, weighting)

        magnitude = None

        # Variables for Overall RMS calculation (Linear Power Spectrum)
        rms_power_spectrum = None
        energy_norm_factor = 1.0

        if multitaper_enabled:
            # --- Multitaper Method ---
            # Get DPSS windows
            windows = self._get_dpss_windows(len(data))  # (K, N)
            K = windows.shape[0]

            if analysis_mode == "Spectrum" or analysis_mode == "PSD":
                # --- Spectrum or PSD Mode ---
                # Calculate PSD for each channel and each window
                # psd = |FFT(x*w)|^2

                psd_accum_0 = np.zeros(len(freqs))
                psd_accum_1 = np.zeros(len(freqs))

                for k in range(K):
                    w = windows[k]

                    # Channel 0
                    fft_0 = fft_manager.rfft(data[:, 0] * w)
                    psd_accum_0 += np.abs(fft_0) ** 2

                    # Channel 1
                    fft_1 = fft_manager.rfft(data[:, 1] * w)
                    psd_accum_1 += np.abs(fft_1) ** 2

                # Average over K windows
                psd_0 = psd_accum_0 / K
                psd_1 = psd_accum_1 / K

                # Apply Channel Selection
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

                # Capture raw power spectrum for Overall RMS
                # psd_target is already |FFT|^2 (averaged).
                if psd_second is not None:
                    rms_power_spectrum = np.column_stack((psd_target, psd_second))
                else:
                    rms_power_spectrum = psd_target

                # Energy normalization for Multitaper (sum(w^2)=1)
                energy_norm_factor = 1.0 / len(data)

                # Convert to Magnitude (Linear)
                if analysis_mode == "PSD":
                    # PSD (V/rtHz)
                    # mag = sqrt(PSD * 2 / fs)
                    norm_factor_sq = 2 / sample_rate
                else:
                    # Spectrum (Peak Amplitude)
                    # mag = sqrt(PSD) / sqrt(N)
                    norm_factor_sq = 1 / len(data)

                magnitudes = []

                # Target
                mag_target = np.sqrt(psd_target * norm_factor_sq)
                magnitudes.append(mag_target)

                # Second (if Dual)
                if psd_second is not None:
                    mag_second = np.sqrt(psd_second * norm_factor_sq)
                    magnitudes.append(mag_second)

                # Combine
                if len(magnitudes) == 1:
                    mag_linear = magnitudes[0]
                else:
                    mag_linear = np.column_stack(magnitudes)

                # Peak -> RMS conversion if Physical Units or SPL
                if analysis_mode == "Spectrum" and display_unit in ["dBV", "dB SPL"]:
                    mag_linear /= np.sqrt(2)

                # Temporal Averaging
                if self._avg_magnitude is None or self._avg_magnitude.shape != mag_linear.shape:
                    self._avg_magnitude = mag_linear
                else:
                    alpha = averaging
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_linear

                magnitude = 20 * np.log10(self._avg_magnitude + 1e-12)

                # Apply API/SPL adjustments
                if display_unit == "dBV":
                    magnitude += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        magnitude += spl_offset_db

            elif analysis_mode == "Cross Spectrum":
                # Average Cross Spectrum over K windows
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
                    alpha = averaging
                    self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * cs_avg

                avg_cs = self._avg_cross_spectrum

                # Normalize and Magnitude
                mag_linear = np.sqrt(np.abs(avg_cs)) / np.sqrt(len(data))

                if display_unit in ["dBV", "dB SPL"]:
                    mag_linear /= np.sqrt(2)

                magnitude = 20 * np.log10(mag_linear + 1e-12)

                # Apply API/SPL adjustments
                if display_unit == "dBV":
                    magnitude += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        magnitude += spl_offset_db

        else:
            # --- Standard Method ---
            # Apply window
            if window_type == "rect":
                window_name = "boxcar"
            elif window_type == "hanning":
                window_name = "hann"
            else:
                window_name = window_type

            # Use cached window (symmetric to match numpy behavior)
            window = get_cached_window(window_name, len(data), fftbins=False)

            # Calculate Window Correction Factor (Amplitude Correction)
            window_correction = 1.0 / np.mean(window)

            # Broadcast window to stereo
            windowed_data = data * window[:, np.newaxis]

            # FFT
            f0 = fft_manager.rfft(windowed_data[:, 0])
            f1 = fft_manager.rfft(windowed_data[:, 1])
            fft_data = np.column_stack((f0, f1))

            # Normalization Factor for Peak Amplitude
            norm_factor = (2.0 / len(data)) * window_correction

            # --- Overall RMS Logic (Standard) ---
            S2 = np.sum(window**2)
            energy_norm_factor = 1.0 / (len(data) * S2)

            # Raw Power Spectrum for RMS (|FFT|^2)
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
            # -----------------------------------

            if analysis_mode == "Spectrum":
                # Standard Spectrum
                mag_stereo = np.abs(fft_data)

                # Channel Selection Logic
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
                    mag_mono = mag_stereo[:, 0]  # Left
                    mag_second = mag_stereo[:, 1]  # Right
                else:
                    mag_mono = np.mean(mag_stereo, axis=1)
                    mag_second = None

                # Normalize to Peak Amplitude
                mag_mono = mag_mono * norm_factor
                if mag_second is not None:
                    mag_second = mag_second * norm_factor

                # If Physical Units (dBV) or SPL are used, we want RMS reading for sine waves
                if display_unit in ["dBV", "dB SPL"]:
                    mag_mono /= np.sqrt(2)
                    if mag_second is not None:
                        mag_second /= np.sqrt(2)

                # Averaging
                current_mag = mag_mono
                if mag_second is not None:
                    current_mag = np.column_stack((mag_mono, mag_second))

                if self._avg_magnitude is None or self._avg_magnitude.shape != current_mag.shape:
                    self._avg_magnitude = current_mag
                else:
                    alpha = averaging
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * current_mag

                magnitude_linear = self._avg_magnitude
                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                # Apply dBV / SPL offsets
                if display_unit == "dBV":
                    magnitude += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        magnitude += spl_offset_db

            elif analysis_mode == "PSD":
                # Power Spectral Density (Voltage Noise Density)
                sum_w = np.sum(window)
                sum_w2 = np.sum(window**2)
                fs = sample_rate

                # Conversion factor from Peak Amplitude to V/rtHz
                psd_factor = sum_w / np.sqrt(2 * fs * sum_w2)

                mag_stereo = np.abs(fft_data)

                # Apply standard normalization first to get Peak Amplitude
                mag_stereo = mag_stereo * norm_factor

                # Apply PSD factor
                mag_stereo = mag_stereo * psd_factor

                # Channel Selection
                if channel_mode == "Left":
                    mag_mono = mag_stereo[:, 0]
                elif channel_mode == "Right":
                    mag_mono = mag_stereo[:, 1]
                elif channel_mode == "Average":
                    # Average the Power (V^2/Hz), then sqrt
                    pow_stereo = mag_stereo**2
                    avg_pow = np.mean(pow_stereo, axis=1)
                    mag_mono = np.sqrt(avg_pow)
                elif channel_mode == "Dual":
                    mag_mono = mag_stereo
                else:
                    mag_mono = mag_stereo[:, 0]

                # Averaging
                if self._avg_magnitude is None or self._avg_magnitude.shape != mag_mono.shape:
                    self._avg_magnitude = mag_mono
                else:
                    alpha = averaging
                    self._avg_magnitude = alpha * self._avg_magnitude + (1 - alpha) * mag_mono

                magnitude_linear = self._avg_magnitude
                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                # Apply API/SPL adjustments
                if display_unit == "dBV":
                    magnitude += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        magnitude += spl_offset_db

            elif analysis_mode == "Cross Spectrum":
                # Cross Spectrum
                F1 = fft_data[:, 0]
                F2 = fft_data[:, 1]
                Sxy = F1 * np.conj(F2)

                # Normalize
                Sxy = Sxy * (norm_factor**2)

                # Complex Averaging
                if self._avg_cross_spectrum is None or self._avg_cross_spectrum.shape != Sxy.shape:
                    self._avg_cross_spectrum = Sxy
                else:
                    alpha = averaging
                    self._avg_cross_spectrum = alpha * self._avg_cross_spectrum + (1 - alpha) * Sxy

                # Magnitude
                avg_Sxy = self._avg_cross_spectrum
                magnitude_linear = np.sqrt(np.abs(avg_Sxy))

                if display_unit in ["dBV", "dB SPL"]:
                    magnitude_linear /= np.sqrt(2)

                magnitude = 20 * np.log10(magnitude_linear + 1e-12)

                # Apply API/SPL adjustments
                if display_unit == "dBV":
                    magnitude += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        magnitude += spl_offset_db

        # Apply Weighting
        if magnitude is not None:
            if magnitude.ndim == 2 and weighting_db.ndim == 1:
                magnitude += weighting_db[:, np.newaxis]
            else:
                magnitude += weighting_db

        # Calculate Accurate Overall Weighted RMS
        overall_weighted_db = -120.0

        if rms_power_spectrum is not None:
            # Convert weighting to Linear Squared (Power Gain)
            w_lin_sq = 10 ** (weighting_db / 10.0)

            # Apply weighting to raw power spectrum
            if rms_power_spectrum.ndim == 2 and w_lin_sq.ndim == 1:
                p_weighted = rms_power_spectrum * w_lin_sq[:, np.newaxis]
            else:
                p_weighted = rms_power_spectrum * w_lin_sq

            # Sum bins in range 20Hz - 20kHz
            mask = (freqs >= 20) & (freqs <= 20000)

            if np.any(mask):
                if p_weighted.ndim == 2:
                    sum_p = 2 * np.sum(p_weighted[mask])
                else:
                    sum_p = 2 * np.sum(p_weighted[mask])

                # Apply Energy Normalization
                current_frame_power = sum_p * energy_norm_factor

                # Temporal Averaging of Power
                if self._avg_weighted_power is None:
                    self._avg_weighted_power = current_frame_power
                else:
                    alpha = averaging
                    if np.isscalar(current_frame_power) and np.isscalar(self._avg_weighted_power):
                        self._avg_weighted_power = alpha * self._avg_weighted_power + (1 - alpha) * current_frame_power
                    else:
                        self._avg_weighted_power = current_frame_power

                # Calculate RMS
                overall_rms_linear = np.sqrt(self._avg_weighted_power)
                overall_weighted_db = 20 * np.log10(overall_rms_linear + 1e-12)

                # Apply Calibration Offsets to final dB value
                if display_unit == "dBV":
                    overall_weighted_db += input_offset_db
                elif display_unit == "dB SPL":
                    if spl_offset_db is not None:
                        overall_weighted_db += spl_offset_db

        # Peak Hold
        if peak_hold and magnitude is not None:
            if self._peak_magnitude is None or self._peak_magnitude.shape != magnitude.shape:
                self._peak_magnitude = magnitude
            else:
                self._peak_magnitude = np.maximum(self._peak_magnitude, magnitude)

        # Smoothing
        fraction_map = {"1/1 Octave": 1, "1/3 Octave": 3, "1/6 Octave": 6, "1/12 Octave": 12, "1/24 Octave": 24}
        fraction = fraction_map.get(octave_smoothing)

        smoothed_freqs = None
        smoothed_mags = None
        smoothed_peak_mags = None

        if fraction:
            smoothed_freqs, smoothed_mags = self.apply_octave_smoothing(freqs, magnitude, fraction)
            if peak_hold and self._peak_magnitude is not None:
                _, smoothed_peak_mags = self.apply_octave_smoothing(freqs, self._peak_magnitude, fraction)
        else:
            # If no smoothing, we just return the raw freqs/mags but maybe minus DC?
            # The widget logic was:
            # plot_freqs = freqs[1:]
            # plot_mags = magnitude[1:]
            # But let's return full arrays and let UI decide what to slice, or slice here.
            # Usually DC (bin 0) is -inf or weird in Log plot.
            pass

        return {
            "freqs": freqs,
            "magnitude": magnitude,
            "peak_magnitude": self._peak_magnitude if peak_hold else None,
            "overall_weighted_db": overall_weighted_db,
            "smoothed_freqs": smoothed_freqs,
            "smoothed_magnitude": smoothed_mags,
            "smoothed_peak_magnitude": smoothed_peak_mags,
        }
