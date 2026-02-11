import functools
import math
import numpy as np
import scipy.signal
import soundfile as sf
from scipy.optimize import minimize_scalar
from scipy.signal import butter, get_window, sosfiltfilt, firwin


from src.core.fft_manager import fft_manager


# A-weighting curve constants (IEC 61672:2003)
# These define the poles and zeros of the analog A-weighting filter
A_WEIGHTING_F1 = 20.6
A_WEIGHTING_F2 = 107.7
A_WEIGHTING_F3 = 737.9
A_WEIGHTING_F4 = 12194.0

# Gain normalization factor to achieve 0 dB at 1 kHz
# 20 * log10(Ra(1000)) approx -2.000 dB
# Gain = 10^(2.000/20) = 1.2589...
A_WEIGHTING_GAIN = 1.2589


@functools.lru_cache(maxsize=16)
def get_cached_window(window_name, nx, dtype=np.float64, fftbins=True):
    return get_window(window_name, nx, fftbins=fftbins).astype(dtype)


@functools.lru_cache(maxsize=128)
def _get_butter_sos(order, Wn, btype, fs=None):
    return butter(order, Wn, btype=btype, fs=fs, output="sos")


def _calculate_ra_raw(f):
    f2 = f**2
    const = A_WEIGHTING_F4**2 * f**4
    denom = (
        (f2 + A_WEIGHTING_F1**2)
        * np.sqrt((f2 + A_WEIGHTING_F2**2) * (f2 + A_WEIGHTING_F3**2))
        * (f2 + A_WEIGHTING_F4**2)
    )
    Ra = const / denom
    return Ra


@functools.lru_cache(maxsize=32)
def _compute_a_weighting_sq_curve(n_bins, step, start_freq=0.0):
    f = start_freq + np.arange(n_bins) * step
    ra = _calculate_ra_raw(f)
    return (ra * A_WEIGHTING_GAIN) ** 2


@functools.lru_cache(maxsize=32)
def _compute_a_weighting_sq_curve_log(n_bins, start_freq, stop_freq):
    if n_bins <= 1:
        f = np.array([start_freq])
    else:
        f = np.geomspace(start_freq, stop_freq, n_bins)
    ra = _calculate_ra_raw(f)
    return (ra * A_WEIGHTING_GAIN) ** 2


@functools.lru_cache(maxsize=32)
def _get_a_weighting_curve_from_bytes(data_bytes, dtype_str, shape):
    freqs = np.frombuffer(data_bytes, dtype=dtype_str).reshape(shape)
    ra = _calculate_ra_raw(freqs)
    return (ra * A_WEIGHTING_GAIN) ** 2


@functools.lru_cache(maxsize=32)
def _get_time_array(N: int, sampling_rate: float) -> np.ndarray:
    """
    Cached time array generation.
    Returns read-only array to prevent modification.
    """
    if sampling_rate <= 0:
        raise ValueError("sampling_rate must be > 0")
    t = np.arange(N, dtype=np.float64)
    t /= sampling_rate
    t.flags.writeable = False
    return t


@functools.lru_cache(maxsize=32)
def _get_reference_signals(
    N: int, sampling_rate: float, frequency: float
) -> tuple[np.ndarray, np.ndarray]:
    """
    Cached reference sine and cosine waves generation.
    Returns read-only arrays to prevent modification.
    """
    t = _get_time_array(N, sampling_rate)
    theta = 2 * np.pi * frequency * t
    sin_ref = np.sin(theta)
    cos_ref = np.cos(theta)
    sin_ref.flags.writeable = False
    cos_ref.flags.writeable = False
    return sin_ref, cos_ref


@functools.lru_cache(maxsize=32)
def _get_resample_filter(up, down, window_type=('kaiser', 5.0)):
    max_rate = max(up, down)
    f_c = 1. / max_rate
    half_len = 10 * max_rate
    return firwin(2 * half_len + 1, f_c, window=window_type)


class AudioCalc:
    """
    Shared audio calculation utilities.
    """
    MAX_AUDIO_SAMPLES = 500_000_000

    @staticmethod
    def validate_audio_file_size(filepath):
        """
        Validates that the audio file size (total samples) does not exceed MAX_AUDIO_SAMPLES.
        Returns (True, "") if valid, or (False, error_message) if invalid.
        """
        try:
            info = sf.info(filepath)
            total_samples = info.frames * info.channels
            if total_samples > AudioCalc.MAX_AUDIO_SAMPLES:
                return False, f"File too large: {total_samples} samples (Max: {AudioCalc.MAX_AUDIO_SAMPLES})"
            return True, ""
        except Exception as e:
            return False, f"Failed to check file size: {e}"

    @staticmethod
    def resample(data, source_sr, target_sr):
        """
        Resamples audio data from source_sr to target_sr using polyphase filtering.
        This is more efficient than Fourier method for large arrays.
        """
        if source_sr <= 0 or target_sr <= 0:
            return data

        if source_sr == target_sr:
            return data

        # Calculate integer ratios for up/down sampling
        gcd = math.gcd(int(source_sr), int(target_sr))
        up = int(target_sr // gcd)
        down = int(source_sr // gcd)

        # resample_poly assumes axis=0 is the time axis, which matches (samples, channels)
        # It handles both 1D and 2D arrays correctly.
        window = _get_resample_filter(up, down)
        return scipy.signal.resample_poly(data, up, down, window=window)

    @staticmethod
    def _apply_filter(signal, sampling_rate, min_len, sos_factory, on_invalid_sos="bypass"):
        """
        Helper to apply SOS filter with length check.
        sos_factory: callable(nyquist) -> sos. Should return None if filter is invalid.
        on_invalid_sos: "bypass" (return signal) or "silence" (return zeros).
        """
        if len(signal) <= min_len:
            return signal

        nyquist = 0.5 * sampling_rate
        sos = sos_factory(nyquist)

        if sos is None:
            if on_invalid_sos == "silence":
                return np.zeros_like(signal)
            else:
                return signal

        return sosfiltfilt(sos, signal)

    @staticmethod
    def bandpass_filter(signal, sampling_rate, lowcut=20.0, highcut=20000.0):
        # Check signal length to ensure padding works (3 * (2 * 8 + 1) = 51)
        def get_sos(nyquist):
            l_clamped = max(0.1, lowcut)
            h_clamped = min(nyquist - 1, highcut)
            if l_clamped >= h_clamped:
                return None
            # Wn must be a tuple to be hashable for lru_cache
            Wn = (l_clamped / nyquist, h_clamped / nyquist)
            return _get_butter_sos(8, Wn, "bandpass")

        return AudioCalc._apply_filter(signal, sampling_rate, 51, get_sos, on_invalid_sos="silence")

    @staticmethod
    def lowpass_filter(signal, sampling_rate, cutoff=20000.0):
        # Check signal length to ensure padding works (3 * (2 * 4 + 1) = 27)
        def get_sos(nyquist):
            c = min(nyquist - 1, max(0.1, cutoff))
            return _get_butter_sos(8, c / nyquist, "lowpass")

        return AudioCalc._apply_filter(signal, sampling_rate, 27, get_sos)

    @staticmethod
    def highpass_filter(signal, sampling_rate, cutoff=20.0):
        # Check signal length to ensure padding works (3 * (2 * 4 + 1) = 27)
        def get_sos(nyquist):
            c = min(nyquist - 1, max(0.1, cutoff))
            return _get_butter_sos(8, c / nyquist, "highpass")

        return AudioCalc._apply_filter(signal, sampling_rate, 27, get_sos)

    @staticmethod
    def notch_filter(signal, sampling_rate, target_frequency, quality_factor=30):
        # Check signal length to ensure padding works (3 * (2 * 2 + 1) = 15)
        def get_sos(nyquist):
            if target_frequency <= 0 or target_frequency >= nyquist:
                return None

            w0 = target_frequency / nyquist
            bandwidth = w0 / quality_factor

            # Validate resulting filter poles
            w_low = w0 - bandwidth / 2
            w_high = w0 + bandwidth / 2

            if w_low <= 0 or w_high >= 1:
                return None

            # Wn must be a tuple to be hashable for lru_cache
            Wn = (w_low, w_high)
            return _get_butter_sos(2, Wn, "bandstop")

        return AudioCalc._apply_filter(signal, sampling_rate, 15, get_sos)

    @staticmethod
    def _sine_fit_residual(f, signal, t, M, fitted_buffer, residual_buffer):
        """
        Calculates the residual MSE for a single frequency f using Sine Fitting.
        Uses pre-allocated buffers M, fitted_buffer, residual_buffer.
        """
        w = 2 * np.pi * f

        # Fill pre-allocated M columns
        np.sin(w * t, out=M[:, 0])
        np.cos(w * t, out=M[:, 1])
        # M[:, 2] is already 1.0

        # Use Normal Equations
        try:
            MT = M.T
            coeffs = np.linalg.solve(MT @ M, MT @ signal)
        except np.linalg.LinAlgError:
            coeffs, _, _, _ = np.linalg.lstsq(M, signal, rcond=None)

        np.matmul(M, coeffs, out=fitted_buffer)
        np.subtract(signal, fitted_buffer, out=residual_buffer)
        np.square(residual_buffer, out=residual_buffer)
        return np.mean(residual_buffer)

    @staticmethod
    def _perform_coarse_search(signal, t, grid):
        """
        Performs a coarse grid search for the best frequency using vectorized
        sufficient statistics accumulation.
        Returns the best frequency from the grid.
        """
        N = len(signal)
        K = len(grid)
        # Accumulators for sufficient statistics
        # G terms: s2, c2, sc, s, c (sum of squares/products)
        acc_G = np.zeros((K, 5), dtype=np.float64)
        # v terms: sig_s, sig_c (dot products with signal)
        acc_v = np.zeros((K, 2), dtype=np.float64)

        # Constant term for the '1' column
        sum_sig = np.sum(signal)

        # Chunked processing to limit memory usage
        chunk_size = 16384
        two_pi = 2 * np.pi

        for i in range(0, N, chunk_size):
            end = min(i + chunk_size, N)
            t_chunk = t[i:end]
            sig_chunk = signal[i:end]

            # Compute phases: (K, chunk_len)
            phases = np.outer(grid, t_chunk) * two_pi

            s_chunk = np.sin(phases)
            c_chunk = np.cos(phases)

            # Update G accumulators
            acc_G[:, 0] += np.sum(s_chunk**2, axis=1)
            acc_G[:, 1] += np.sum(c_chunk**2, axis=1)
            acc_G[:, 2] += np.sum(s_chunk * c_chunk, axis=1)
            acc_G[:, 3] += np.sum(s_chunk, axis=1)
            acc_G[:, 4] += np.sum(c_chunk, axis=1)

            # Update v accumulators
            acc_v[:, 0] += s_chunk @ sig_chunk
            acc_v[:, 1] += c_chunk @ sig_chunk

        best_score = -1.0
        best_coarse = grid[0] if len(grid) > 0 else 0.0

        # Reusing arrays for system solution
        G = np.empty((3, 3), dtype=np.float64)
        v = np.empty(3, dtype=np.float64)

        # Fill constant part of G
        G[2, 2] = N
        v[2] = sum_sig

        for k in range(K):
            s2, c2, sc, s_sum, c_sum = acc_G[k]
            sig_s, sig_c = acc_v[k]

            G[0, 0] = s2
            G[0, 1] = sc
            G[0, 2] = s_sum
            G[1, 0] = sc
            G[1, 1] = c2
            G[1, 2] = c_sum
            G[2, 0] = s_sum
            G[2, 1] = c_sum
            # G[2, 2] is N (set outside loop)

            v[0] = sig_s
            v[1] = sig_c
            # v[2] is sum_sig (set outside loop)

            try:
                x = np.linalg.solve(G, v)
                score = np.dot(x, v)
            except np.linalg.LinAlgError:
                x, _, _, _ = np.linalg.lstsq(G, v, rcond=None)
                score = np.dot(x, v)

            if score > best_score:
                best_score = score
                best_coarse = grid[k]

        return best_coarse

    @staticmethod
    def optimize_frequency(signal, sampling_rate, freq_guess, return_full=False):
        """
        Optimizes frequency estimate using Sine Fitting (minimizing residual RMS).
        """
        N = len(signal)
        if N == 0 or sampling_rate <= 0:
            if return_full:
                return freq_guess, None, None
            return freq_guess

        if not np.isfinite(freq_guess):
            # We can't do full FFT here easily without refactoring, so we rely on caller or return
            if return_full:
                return freq_guess, None, None
            return freq_guess

        t = _get_time_array(N, sampling_rate)

        # Pre-allocate arrays to avoid repeated allocation in loop
        M = np.empty((N, 3), dtype=t.dtype)
        M[:, 2] = 1.0  # The 'ones' column is constant

        # Pre-allocate working buffers for fitting to avoid loop allocations
        fitted_buffer = np.empty(N, dtype=t.dtype)
        residual_buffer = np.empty(N, dtype=t.dtype)

        def get_residual_mse(f):
            return AudioCalc._sine_fit_residual(f, signal, t, M, fitted_buffer, residual_buffer)

        # Search around guess
        bin_width = sampling_rate / N
        search_width = max(5.0 * bin_width, 5.0)

        bounds = (freq_guess - search_width, freq_guess + search_width)

        # Pass 1: Coarse Search (Grid Search)
        step = max(bin_width / 2.0, 0.1)  # at least 0.1Hz step
        if bounds[1] > bounds[0]:
            grid = np.arange(bounds[0], bounds[1] + step, step)
        else:
            grid = np.array([freq_guess])

        # Filter negative frequencies
        grid = grid[grid > 0]

        if len(grid) > 0:
            best_coarse = AudioCalc._perform_coarse_search(signal, t, grid)
        else:
            best_coarse = freq_guess

        # Pass 2: Fine Search (Zoom in)
        zoom_width = step * 1.5
        bounds_fine = (max(0.1, best_coarse - zoom_width), best_coarse + zoom_width)
        res_fine = minimize_scalar(get_residual_mse, bounds=bounds_fine, method="bounded", options={'xatol': 1e-14})
        best_freq = res_fine.x

        if return_full:
            # Re-compute coeffs for the best frequency
            w = 2 * np.pi * best_freq
            np.sin(w * t, out=M[:, 0])
            np.cos(w * t, out=M[:, 1])
            try:
                # Use lstsq for final calculation for maximum stability/precision
                coeffs, _, _, _ = np.linalg.lstsq(M, signal, rcond=None)
            except np.linalg.LinAlgError:
                # Fallback to solve if lstsq fails (unlikely)
                MT = M.T
                coeffs = np.linalg.solve(MT @ M, MT @ signal)
            return best_freq, coeffs, M

        return best_freq

    @staticmethod
    def calculate_thdn_sine_fit(signal, sampling_rate, freq_guess):
        """
        Calculates THD+N using Sine Fitting method.
        Returns (thdn_db, fund_rms, noise_dist_rms)
        """
        N = len(signal)

        # 1. Optimize Frequency
        best_freq, coeffs, M = AudioCalc.optimize_frequency(signal, sampling_rate, freq_guess, return_full=True)

        if not np.isfinite(best_freq) or M is None or coeffs is None:
            return -140.0, 0.0, 0.0

        # 2. Get Final Residual
        fitted_fund = M @ coeffs
        residual = signal - fitted_fund

        # 3. Bandwidth Limit Residual (20Hz - 20kHz)
        # Highpass 20Hz (Remove DC/Drift if any left)
        # Only filter if we have enough samples to support padding (padlen > 15)
        if N > 18:
            if sampling_rate > 40:
                sos_hp = _get_butter_sos(4, 20, "hp", fs=sampling_rate)
                residual = sosfiltfilt(sos_hp, residual)

            # Lowpass 20kHz
            if sampling_rate > 44100:
                sos_lp = _get_butter_sos(4, 20000, "lp", fs=sampling_rate)
                residual = sosfiltfilt(sos_lp, residual)

        # 4. Calculate RMS
        # Trim edges to avoid filter transients from bandwidth limit (especially 20Hz HPF)
        # 4. Calculate RMS
        # Trim edges to avoid filter transients from bandwidth limit
        # sosfiltfilt (zero-phase) spreads transients to both start and end.
        # 4th order filter at 20Hz/48kHz has long settling time.
        # 100ms trim is safer for precision measurements if length permits.
        trim_samples = int(sampling_rate * 0.1)  # 100ms

        # Ensure we don't trim more than 25% of the data total (12.5% each side)
        max_trim = N // 8
        trim = min(trim_samples, max_trim)

        if trim > 0 and N > 2 * trim:
            nd_rms = np.sqrt(np.mean(residual[trim:-trim] ** 2))
            fund_rms = np.sqrt(np.mean(fitted_fund[trim:-trim] ** 2))
        else:
            nd_rms = np.sqrt(np.mean(residual**2))
            fund_rms = np.sqrt(np.mean(fitted_fund**2))

        if fund_rms == 0:
            return -140.0, 0.0, 0.0

        ratio = nd_rms / fund_rms
        thdn_db = 20 * np.log10(ratio + 1e-12)

        return thdn_db, fund_rms, nd_rms

    @staticmethod
    def _analyze_fundamental(freqs, amplitude_spectrum, fundamental_freq, search_window):
        """Finds the fundamental frequency and amplitude."""
        idx_min = np.searchsorted(freqs, fundamental_freq - search_window)
        idx_max = np.searchsorted(freqs, fundamental_freq + search_window)
        if idx_max <= idx_min:
            idx_max = idx_min + 1

        # Find max in range
        if idx_max < len(amplitude_spectrum):
            subset = amplitude_spectrum[idx_min:idx_max]
            if len(subset) > 0:
                local_max_idx = np.argmax(subset)
                peak_idx = idx_min + local_max_idx
            else:
                peak_idx = np.argmin(np.abs(freqs - fundamental_freq))
        else:
            peak_idx = np.argmin(np.abs(freqs - fundamental_freq))

        max_freq = freqs[peak_idx]
        max_amplitude = amplitude_spectrum[peak_idx]

        # Refine Frequency using Parabolic Interpolation
        if 0 < peak_idx < len(amplitude_spectrum) - 1:
            alpha = amplitude_spectrum[peak_idx - 1]
            beta = amplitude_spectrum[peak_idx]
            gamma = amplitude_spectrum[peak_idx + 1]

            denom = alpha - 2 * beta + gamma
            if denom != 0:
                p = 0.5 * (alpha - gamma) / denom
                max_freq = freqs[peak_idx] + p * (freqs[1] - freqs[0])
                # Optional: Refine amplitude estimate
                # max_amplitude = beta - 0.25 * (alpha - gamma) * p

        return max_freq, max_amplitude

    @staticmethod
    def _analyze_harmonics_list(
        freqs, amplitude_spectrum, max_freq, max_amplitude, sampling_rate, search_window, min_db
    ):
        """Calculates harmonics properties."""
        harmonic_results = []
        harmonic_amplitudes_linear = []

        # Up to 10th harmonic
        for i in range(2, 11):
            harmonic_freq = max_freq * i
            if harmonic_freq >= sampling_rate / 2:
                break

            # Search near harmonic
            h_idx_min = np.searchsorted(freqs, harmonic_freq - search_window)
            h_idx_max = np.searchsorted(freqs, harmonic_freq + search_window)

            if h_idx_max < len(amplitude_spectrum) and h_idx_max > h_idx_min:
                subset = amplitude_spectrum[h_idx_min:h_idx_max]
                local_max_h = np.argmax(subset)
                h_peak_idx = h_idx_min + local_max_h

                h_amp = amplitude_spectrum[h_peak_idx]
                h_freq = freqs[h_peak_idx]

                relative_amp = h_amp / max_amplitude if max_amplitude > 0 else 0
                amp_db = 20 * np.log10(relative_amp + 1e-12)

                harmonic_results.append(
                    {
                        "order": i,
                        "frequency": h_freq,
                        "amplitude_dbr": amp_db,
                        "amplitude_linear": h_amp,
                    }
                )
                harmonic_amplitudes_linear.append(h_amp)
            else:
                harmonic_results.append(
                    {
                        "order": i,
                        "frequency": harmonic_freq,
                        "amplitude_dbr": min_db,
                        "amplitude_linear": 0,
                    }
                )
        return harmonic_results, harmonic_amplitudes_linear

    @staticmethod
    def _calculate_thd(max_amplitude, harmonic_amplitudes_linear, min_db):
        """Calculates Total Harmonic Distortion (THD)."""
        if max_amplitude > 0:
            if harmonic_amplitudes_linear:
                thd_linear = np.sqrt(np.sum(np.square(harmonic_amplitudes_linear))) / max_amplitude
            else:
                thd_linear = 0.0
            thd_percent = thd_linear * 100
            thd_db = 20 * np.log10(thd_linear + 1e-12)
        else:
            thd_percent = 0
            thd_db = min_db
        return thd_percent, thd_db

    @staticmethod
    def _calculate_thdn_and_sinad(audio_data, sampling_rate, max_freq):
        """Calculates THD+N and SINAD."""
        thdn_db, fund_rms, res_rms = AudioCalc.calculate_thdn_sine_fit(
            audio_data, sampling_rate, max_freq
        )
        thdn_linear = 10 ** (thdn_db / 20)

        thdn_percent = thdn_linear * 100
        sinad_db = -thdn_db
        return thdn_percent, thdn_db, sinad_db, fund_rms, res_rms

    @staticmethod
    def analyze_harmonics(
        audio_data, fundamental_freq, window_name, sampling_rate, min_db=-140.0
    ):
        window = get_cached_window(window_name, len(audio_data), dtype=audio_data.dtype)
        windowed_data = audio_data * window
        fft_result = fft_manager.rfft(windowed_data)
        freqs = fft_manager.rfftfreq(len(audio_data), 1 / sampling_rate)

        # Coherent gain correction
        coherent_gain = np.sum(window) / len(window)

        # Amplitude spectrum (Peak)
        # rfft returns N/2+1 bins. Magnitude is |X|/N * 2 (except DC and Nyquist)
        amplitude_spectrum = (np.abs(fft_result) / len(audio_data)) * 2 / coherent_gain

        # Determine search window
        if len(freqs) > 1:
            bin_width = freqs[1] - freqs[0]
        else:
            bin_width = 1.0

        # Ensure window is wide enough for low freq (at least 5 bins)
        search_window = max(0.15 * fundamental_freq, 5.0 * bin_width)

        # 1. Find Fundamental Peak
        max_freq, max_amplitude = AudioCalc._analyze_fundamental(
            freqs, amplitude_spectrum, fundamental_freq, search_window
        )

        amp_dbfs = 20 * np.log10(max_amplitude + 1e-12)
        basic_wave_result = {
            "frequency": max_freq,
            "amplitude_dbfs": amp_dbfs,
            "max_amplitude": max_amplitude,
        }

        # 2. Harmonics
        harmonic_results, harmonic_amplitudes_linear = AudioCalc._analyze_harmonics_list(
            freqs,
            amplitude_spectrum,
            max_freq,
            max_amplitude,
            sampling_rate,
            search_window,
            min_db,
        )

        # 3. THD Calculation
        thd_percent, thd_db = AudioCalc._calculate_thd(
            max_amplitude, harmonic_amplitudes_linear, min_db
        )

        # 4. THD+N Calculation (Sine Fit)
        # Use raw audio_data (no window applied yet)
        thdn_percent, thdn_db, sinad_db, fund_rms, res_rms = (
            AudioCalc._calculate_thdn_and_sinad(audio_data, sampling_rate, max_freq)
        )

        return {
            "basic_wave": basic_wave_result,
            "harmonics": harmonic_results,
            "thd_percent": thd_percent,
            "thd_db": thd_db,
            "thdn_percent": thdn_percent,
            "thdn_db": thdn_db,
            "sinad_db": sinad_db,
            # Raw components for averaging
            "raw_fund_rms": fund_rms,
            "raw_res_rms": res_rms,
            "raw_harmonics": harmonic_amplitudes_linear,
            "raw_fund_amp": max_amplitude,
            "fft_data": fft_result,
        }

    @staticmethod
    def _find_peak(mag, freqs, target_freq, width=20.0):
        # Optimized using searchsorted since freqs is sorted
        f_start = target_freq - width
        f_end = target_freq + width

        idx_start = np.searchsorted(freqs, f_start, side="left")
        idx_end = np.searchsorted(freqs, f_end, side="right")

        if idx_start >= idx_end:
            return 0.0

        return np.max(mag[idx_start:idx_end])

    @staticmethod
    def calculate_imd_smpte(mag, freqs, f1, f2, num_sidebands=3):
        # SMPTE: f1 (low), f2 (high). IMD products at f2 +/- n*f1
        amp_f2 = AudioCalc._find_peak(mag, freqs, f2, width=max(50.0, f1 * 0.1))

        if amp_f2 < 1e-6:
            return {"imd": 0.0, "imd_db": -100.0}

        sum_sq_sidebands = 0.0
        for n in range(1, num_sidebands + 1):
            sb_upper = f2 + n * f1
            sb_lower = f2 - n * f1

            amp_upper = AudioCalc._find_peak(mag, freqs, sb_upper)
            amp_lower = AudioCalc._find_peak(mag, freqs, sb_lower)

            sum_sq_sidebands += amp_upper**2 + amp_lower**2

        imd = np.sqrt(sum_sq_sidebands) / amp_f2
        return {"imd": imd * 100, "imd_db": 20 * np.log10(imd) if imd > 1e-9 else -100.0}

    @staticmethod
    def calculate_imd_ccif(mag, freqs, f1, f2):
        # CCIF: f1, f2 close (e.g. 19k, 20k).
        # d2 = f2 - f1
        # d3 = 2f1 - f2, 2f2 - f1

        amp_f1 = AudioCalc._find_peak(mag, freqs, f1)
        amp_f2 = AudioCalc._find_peak(mag, freqs, f2)
        total_amp = amp_f1 + amp_f2

        if total_amp < 1e-6:
            return {"imd": 0.0, "imd_db": -100.0}

        # d2
        d2_freq = abs(f2 - f1)
        amp_d2 = AudioCalc._find_peak(mag, freqs, d2_freq)

        # d3
        d3_low = 2 * f1 - f2
        d3_high = 2 * f2 - f1
        amp_d3_low = AudioCalc._find_peak(mag, freqs, d3_low) if d3_low > 0 else 0
        amp_d3_high = AudioCalc._find_peak(mag, freqs, d3_high)

        distortion_sum_sq = amp_d2**2 + amp_d3_low**2 + amp_d3_high**2
        imd = np.sqrt(distortion_sum_sq) / total_amp

        return {"imd": imd * 100, "imd_db": 20 * np.log10(imd) if imd > 1e-9 else -100.0}

    @staticmethod
    def calculate_multitone_tdn(mag, freqs, tone_freqs, window_width_pct=0.05):
        """
        Calculates Multi-tone TD+N.
        mag: Linear magnitude spectrum
        freqs: Frequency bins
        tone_freqs: List of expected tone frequencies
        """
        # Use a mask to identify bins belonging to tones
        is_tone_bin = np.zeros(len(mag), dtype=bool)

        # Vectorized searchsorted
        tone_freqs_arr = np.asarray(tone_freqs)
        widths = np.maximum(10.0, tone_freqs_arr * window_width_pct)

        start_freqs = tone_freqs_arr - widths
        end_freqs = tone_freqs_arr + widths

        idx_mins = np.searchsorted(freqs, start_freqs, side="left")
        idx_maxs = np.searchsorted(freqs, end_freqs, side="right")

        peak_indices = []
        for i in range(len(tone_freqs_arr)):
            idx_min = idx_mins[i]
            idx_max = idx_maxs[i]

            if idx_max > idx_min:
                subset_mag = mag[idx_min:idx_max]
                # argmax on empty slice raises error, but checked idx_max > idx_min
                local_peak_idx_rel = np.argmax(subset_mag)
                peak_idx = idx_min + local_peak_idx_rel
                peak_indices.append(peak_idx)

        # Mark bins around peak as tone
        # Blackman-Harris main lobe is approx +/- 4 bins
        if peak_indices:
            peak_indices_arr = np.array(peak_indices)
            offsets = np.arange(-4, 5)
            # Broadcast to shape (N_peaks, 9)
            mask_indices = peak_indices_arr[:, None] + offsets[None, :]
            # Flatten
            mask_indices_flat = mask_indices.ravel()
            # Clip/Filter valid indices
            mask_indices_valid = mask_indices_flat[(mask_indices_flat >= 0) & (mask_indices_flat < len(mag))]
            is_tone_bin[mask_indices_valid] = True

        # Calculate Energies
        # We can sum squares directly
        mag_sq = mag**2
        tone_energy = np.sum(mag_sq[is_tone_bin])
        # Use reduce with where to avoid huge temporary allocation for noise bins
        noise_energy = np.add.reduce(mag_sq, where=~is_tone_bin)

        if tone_energy <= 1e-12:
            return {"tdn": 0.0, "tdn_db": -100.0}

        tdn = np.sqrt(noise_energy / tone_energy)

        return {"tdn": tdn * 100, "tdn_db": 20 * np.log10(tdn) if tdn > 1e-9 else -100.0}

    @staticmethod
    def calculate_spdr(mag, freqs, fundamental_freq, window_width_pct=0.1):
        """
        Calculates Spurious-Free Dynamic Range (SPDR).
        SPDR is the ratio of the fundamental signal power to the power of the
        largest spurious signal (harmonic or non-harmonic).
        """
        # Find Fundamental Peak
        width = max(10.0, fundamental_freq * window_width_pct)
        fund_mask = (freqs >= fundamental_freq - width) & (freqs <= fundamental_freq + width)

        if not np.any(fund_mask):
            return {"spdr_db": 0.0, "max_spur_freq": 0.0, "max_spur_amp": 0.0}

        fund_amp = np.max(mag[fund_mask])

        if fund_amp < 1e-9:
            return {"spdr_db": 0.0, "max_spur_freq": 0.0, "max_spur_amp": 0.0}

        # Mask out fundamental for spur search
        # We also typically mask out DC
        search_mask = (freqs > 20.0) & ~fund_mask

        if not np.any(search_mask):
            return {"spdr_db": 100.0, "max_spur_freq": 0.0, "max_spur_amp": 0.0}

        # Find max spur
        spur_idx_rel = np.argmax(mag[search_mask])
        spur_idxs = np.where(search_mask)[0]
        spur_idx = spur_idxs[spur_idx_rel]

        spur_amp = mag[spur_idx]
        spur_freq = freqs[spur_idx]

        if spur_amp < 1e-12:
            spdr_db = 140.0  # High dynamic range
        else:
            spdr_db = 20 * np.log10(fund_amp / spur_amp)

        return {"spdr_db": spdr_db, "max_spur_freq": spur_freq, "max_spur_amp": spur_amp}

    @staticmethod
    def calculate_pim(mag, freqs, f1, f2, order=3):
        """
        Calculates Passive Intermodulation (PIM) / Phase Intermodulation.
        For 2-tone test, PIM usually manifests as IMD products.
        This implementation focuses on odd-order IMD products which are typical for PIM.
        """
        # Similar to IMD CCIF/SMPTE but we look for specific PIM orders (IM3, IM5, IM7)
        # IM3: 2f1 - f2, 2f2 - f1
        # IM5: 3f1 - 2f2, 3f2 - 2f1
        # IM7: 4f1 - 3f2, 4f2 - 3f1

        # Find carrier amplitudes
        amp_f1 = AudioCalc._find_peak(mag, freqs, f1)
        amp_f2 = AudioCalc._find_peak(mag, freqs, f2)
        carrier_amp = (amp_f1 + amp_f2) / 2  # Average carrier power

        if carrier_amp < 1e-6:
            return {"pim_db": -100.0, "products": []}

        products = []
        sum_sq_pim = 0.0

        # Calculate up to specified order (must be odd)
        for n in range(3, order + 2, 2):
            # n is order (3, 5, 7...)
            # For order n, coeffs sum to 1? No.
            # IM3: 2,-1 (sum 1).
            # IM5: 3,-2 (sum 1).
            # General: k * f1 - (k-1) * f2
            # where 2k - 1 = n => k = (n+1)/2

            k = (n + 1) // 2
            m = k - 1

            # Lower side
            im_low = k * f1 - m * f2
            # Upper side
            im_high = k * f2 - m * f1

            amp_low = AudioCalc._find_peak(mag, freqs, im_low) if im_low > 0 else 0
            amp_high = AudioCalc._find_peak(mag, freqs, im_high)

            sum_sq_pim += amp_low**2 + amp_high**2

            products.append(
                {"order": n, "freq_low": im_low, "amp_low": amp_low, "freq_high": im_high, "amp_high": amp_high}
            )

        pim_rms = np.sqrt(sum_sq_pim)

        if pim_rms < 1e-12:
            pim_db = -140.0
        else:
            # PIM is often relative to carrier power (dBc)
            pim_db = 20 * np.log10(pim_rms / carrier_amp)

        return {"pim_db": pim_db, "products": products}

    @staticmethod
    def _get_freq_index(freqs, f, is_linear_freqs, freq_step, start_freq=0.0, side="left"):
        if is_linear_freqs:
            val = (f - start_freq) / freq_step
            if side == "left":
                idx = int(math.ceil(val))
            else:
                idx = int(math.floor(val)) + 1
            return max(0, min(idx, len(freqs)))
        else:
            return np.searchsorted(freqs, f, side=side)

    @staticmethod
    def _calculate_hum_noise(mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq=0.0):
        def get_power_in_band(f_center, width=5.0):
            f_start = f_center - width
            f_end = f_center + width

            idx_start = AudioCalc._get_freq_index(freqs, f_start, is_linear_freqs, freq_step, start_freq, side="left")
            idx_end = AudioCalc._get_freq_index(freqs, f_end, is_linear_freqs, freq_step, start_freq, side="right")

            if idx_start >= idx_end:
                return 0.0

            # Integration: Power = sum(PSD * bin_width)
            # mag is V/rtHz. mag_sq is V^2/Hz (PSD).
            power = np.sum(mag_sq[idx_start:idx_end]) * bin_width
            return power

        p50 = get_power_in_band(50.0)
        p60 = get_power_in_band(60.0)

        base_freq = 50.0 if p50 > p60 else 60.0

        # Sum harmonics
        hum_power = 0.0
        hum_components = []
        for i in range(1, 11):  # Fundamental + 9 harmonics
            f_h = base_freq * i
            if f_h > sampling_rate / 2:
                break
            p_h = get_power_in_band(f_h)
            hum_power += p_h
            hum_components.append((f_h, np.sqrt(p_h)))

        return np.sqrt(hum_power), base_freq, hum_components

    @staticmethod
    def _calculate_white_noise(mag, freqs, is_linear_freqs, freq_step, start_freq=0.0):
        i_white_start = AudioCalc._get_freq_index(freqs, 1000.0, is_linear_freqs, freq_step, start_freq, side="left")
        i_white_end = AudioCalc._get_freq_index(freqs, 20000.0, is_linear_freqs, freq_step, start_freq, side="right")

        if i_white_start < i_white_end:
            # Median is robust to peaks, but under-estimates RMS of Gaussian noise (Rayleigh magnitude)
            # Factor: RMS / Median = 1 / sqrt(ln(2)) ~= 1.2011
            white_density = np.median(mag[i_white_start:i_white_end]) * 1.2011
        else:
            white_density = 1e-9  # Fallback
        return white_density

    @staticmethod
    def _calculate_1f_noise(mag, freqs, hum_components, white_density, is_linear_freqs, freq_step, start_freq=0.0):
        results = {}

        # Determine Fit Upper Bound
        # Find first frequency where mag < white_density * 1.5 (approx 3.5dB margin)
        # Search in 1Hz - 1kHz range
        i_search_start = AudioCalc._get_freq_index(freqs, 1.0, is_linear_freqs, freq_step, start_freq, side="left")
        i_search_end = AudioCalc._get_freq_index(freqs, 1000.0, is_linear_freqs, freq_step, start_freq, side="right")

        search_freqs = freqs[i_search_start:i_search_end]
        search_mags = mag[i_search_start:i_search_end]

        # Smooth magnitudes slightly to avoid triggering on dips
        # Simple moving average of 3 bins
        if len(search_mags) > 3:
            search_mags_smooth = np.convolve(search_mags, np.ones(3) / 3, mode="same")
        else:
            search_mags_smooth = search_mags

        # Find knee
        knee_indices = np.where(search_mags_smooth < white_density * 2.0)[0]
        if len(knee_indices) > 0:
            f_knee = search_freqs[knee_indices[0]]
        else:
            f_knee = 100.0  # Default if never drops

        # Clamp knee
        f_max_fit = np.clip(f_knee, 5.0, 400.0)  # Minimum 5Hz range, max 400Hz

        # Fit 1/f
        # Range: 1Hz to f_max_fit
        # Exclude Hum regions
        mask_1f = (freqs >= 1.0) & (freqs <= f_max_fit)

        # Exclude hum
        for h_freq, _h_amp in hum_components:
            f_start = h_freq - 5.0
            f_end = h_freq + 5.0
            idx_start = AudioCalc._get_freq_index(freqs, f_start, is_linear_freqs, freq_step, start_freq, side="left")
            idx_end = AudioCalc._get_freq_index(freqs, f_end, is_linear_freqs, freq_step, start_freq, side="right")
            mask_1f[idx_start:idx_end] = False

        if np.sum(mask_1f) > 5:
            f_log = np.log10(freqs[mask_1f])
            m_log = np.log10(mag[mask_1f] + 1e-15)

            # Linear regression: m_log = slope * f_log + intercept
            slope, intercept = np.polyfit(f_log, m_log, 1)
            results["flicker_slope"] = slope
            results["flicker_intercept"] = intercept
        else:
            results["flicker_slope"] = 0.0
            results["flicker_intercept"] = 0.0

        # Calculate Corner Frequency
        if results["flicker_slope"] != 0:
            log_white = np.log10(white_density + 1e-15)
            x_c = (log_white - results["flicker_intercept"]) / results["flicker_slope"]

            if x_c > 9:
                results["corner_freq"] = 1e9
            elif x_c < -9:
                results["corner_freq"] = 1e-9
            else:
                results["corner_freq"] = 10**x_c
        else:
            results["corner_freq"] = 0.0

        # Explicit 1/f Power Calculation
        # Integrate the fitted 1/f curve from 20Hz to 20kHz (or Corner Freq)
        # Power density P(f) = (10^(slope*log10(f) + intercept))^2
        # P(f) = 10^(2*intercept) * f^(2*slope)
        # Integral P(f) df = C * [ f^(2*slope + 1) / (2*slope + 1) ]

        if results["flicker_slope"] != 0:
            # We integrate 1/f component over the full audio bandwidth (20Hz-20kHz)
            # because physically 1/f noise exists at all frequencies, even if buried under white noise.
            f_start = 20.0
            f_end = 20000.0

            if f_end > f_start:
                A = 10 ** (results["flicker_intercept"])
                alpha = results["flicker_slope"]
                # Density V(f) = A * f^alpha
                # Power Density S(f) = V(f)^2 = A^2 * f^(2*alpha)

                # Integral of x^k is x^(k+1)/(k+1)
                k = 2 * alpha
                C = A**2

                if abs(k + 1) < 1e-9:  # 1/f case (slope -0.5 -> k=-1)
                    # Integral is ln(f)
                    power_flicker = C * (np.log(f_end) - np.log(f_start))
                else:
                    power_flicker = C * ((f_end ** (k + 1)) - (f_start ** (k + 1))) / (k + 1)

                results["flicker_rms"] = np.sqrt(max(0, power_flicker))
            else:
                results["flicker_rms"] = 0.0
        else:
            results["flicker_rms"] = 0.0

        return results

    @staticmethod
    def _calculate_integrated_noise(mag_sq, freqs, bin_width, is_linear_freqs, freq_step, start_freq=0.0):
        def integrate_band(f_start, f_end):
            idx_start = AudioCalc._get_freq_index(freqs, f_start, is_linear_freqs, freq_step, start_freq, side="left")
            idx_end = AudioCalc._get_freq_index(freqs, f_end, is_linear_freqs, freq_step, start_freq, side="left")

            if idx_start >= idx_end:
                return 0.0
            # bin_width is pre-calculated
            return np.sqrt(np.sum(mag_sq[idx_start:idx_end]) * bin_width)

        rms_20k = integrate_band(20, 20000)
        rms_100k = integrate_band(20, 100000)
        return rms_20k, rms_100k

    @staticmethod
    def _calculate_peak_noise(mag, freqs, is_linear_freqs, freq_step, start_freq=0.0):
        # Peak Detection
        # Find peak in 20Hz-20kHz
        i_peak_start = AudioCalc._get_freq_index(freqs, 20.0, is_linear_freqs, freq_step, start_freq, side="left")
        i_peak_end = AudioCalc._get_freq_index(freqs, 20000.0, is_linear_freqs, freq_step, start_freq, side="right")

        # Exclude Hum regions from peak search (optional, but requested to find "Other" noise)
        # If we want the absolute peak, we shouldn't exclude hum.
        # But user asked for "Other" noise.
        # Let's find the absolute peak first.
        if i_peak_start < i_peak_end:
            peak_mags_slice = mag[i_peak_start:i_peak_end]
            peak_idx_rel = np.argmax(peak_mags_slice)

            peak_freq = freqs[i_peak_start + peak_idx_rel]
            peak_amp = peak_mags_slice[peak_idx_rel]
        else:
            peak_freq = 0.0
            peak_amp = 0.0
        return peak_freq, peak_amp

    @staticmethod
    def _calculate_a_weighted_noise(mag_sq, freqs, bin_width, is_linear_freqs, freq_step, is_log_freqs=False, start_freq=0.0, stop_freq=0.0):
        # A-weighting Integration
        # Ra(f) = (12194^2 * f^4) / ((f^2 + 20.6^2) * sqrt((f^2 + 107.7^2)(f^2 + 737.9^2)) * (f^2 + 12194^2))
        # Gain = 20*log10(Ra(f)) + 2.00
        # Linear Gain = Ra(f) * 10^(2.0/20) = Ra(f) * 1.2589

        # Optimization: Use cached A-weighting curve based on frequency array content
        if is_linear_freqs:
            weighting_sq = _compute_a_weighting_sq_curve(len(freqs), freq_step, start_freq)
        elif is_log_freqs:
            weighting_sq = _compute_a_weighting_sq_curve_log(len(freqs), start_freq, stop_freq)
        else:
            # Fallback to content-based caching for arbitrary frequency arrays
            weighting_sq = _get_a_weighting_curve_from_bytes(
                freqs.tobytes(), str(freqs.dtype), freqs.shape
            )

        # Integrate A-weighted spectrum (20Hz - 20kHz)
        i_a_start = AudioCalc._get_freq_index(freqs, 20.0, is_linear_freqs, freq_step, start_freq, side="left")
        i_a_end = AudioCalc._get_freq_index(freqs, 20000.0, is_linear_freqs, freq_step, start_freq, side="right")

        # Integration
        # Power = sum(PSD * Weight^2 * bin_width)
        # Avoid allocating full weighted magnitude array
        weighted_power_slice = mag_sq[i_a_start:i_a_end] * weighting_sq[i_a_start:i_a_end]
        power_a = np.sum(weighted_power_slice) * bin_width

        return np.sqrt(power_a)

    @staticmethod
    def calculate_noise_profile(mag, freqs, sampling_rate):
        """
        Calculates noise profile including Hum, White, and 1/f noise.
        mag: Magnitude spectrum (Linear V/rtHz)
        freqs: Frequency bins
        """
        results = {}

        # Optimization: Check if freqs is linear or logarithmic
        is_linear_freqs = False
        is_log_freqs = False
        freq_step = 1.0
        start_freq = 0.0
        stop_freq = 0.0

        if len(freqs) > 1:
            start_freq = freqs[0]
            # Assume linear step from first two bins
            freq_step = freqs[1] - start_freq
            expected_end = start_freq + freq_step * (len(freqs) - 1)

            # Check approximate linearity
            # Use absolute tolerance suitable for frequency precision
            if abs(freqs[-1] - expected_end) < 1e-5:
                is_linear_freqs = True
            elif start_freq > 1e-9:
                # Check for logarithmic spacing (geometric progression)
                # ratio = f[1] / f[0]
                ratio = freqs[1] / start_freq
                # expected_end = start * ratio^(n-1)
                # Use log space calculation to avoid overflow/precision issues with huge exponents?
                # For audio range (20Hz-20kHz), direct power is fine.
                expected_log_end = start_freq * (ratio ** (len(freqs) - 1))
                if abs(freqs[-1] - expected_log_end) < 1e-4 * expected_log_end:
                    is_log_freqs = True
                    stop_freq = freqs[-1]

        # Pre-calculate squared magnitude and bin width
        mag_sq = mag**2
        bin_width = freq_step if is_linear_freqs else (freqs[1] - freqs[0] if len(freqs) > 1 else 1.0)

        # 1. Hum Noise Detection (50Hz vs 60Hz)
        hum_rms, hum_freq, hum_components = AudioCalc._calculate_hum_noise(
            mag_sq, freqs, sampling_rate, bin_width, is_linear_freqs, freq_step, start_freq
        )
        results["hum_rms"] = hum_rms
        results["hum_freq"] = hum_freq
        results["hum_components"] = hum_components

        # 2. 1/f Noise Analysis & White Noise
        # Estimate White Noise (Median of 1k-20k)
        white_density = AudioCalc._calculate_white_noise(mag, freqs, is_linear_freqs, freq_step, start_freq)
        results["white_density"] = white_density  # V/rtHz

        flicker_results = AudioCalc._calculate_1f_noise(
            mag, freqs, hum_components, white_density, is_linear_freqs, freq_step, start_freq
        )
        results.update(flicker_results)

        # 4. Integrated Noise in Bands
        rms_20k, rms_100k = AudioCalc._calculate_integrated_noise(
            mag_sq, freqs, bin_width, is_linear_freqs, freq_step, start_freq
        )
        results["noise_rms_20k"] = rms_20k
        results["noise_rms_100k"] = rms_100k

        # Peak Detection
        peak_freq, peak_amp = AudioCalc._calculate_peak_noise(mag, freqs, is_linear_freqs, freq_step, start_freq)
        results["peak_freq"] = peak_freq
        results["peak_amp"] = peak_amp

        # A-weighting Integration
        rms_a = AudioCalc._calculate_a_weighted_noise(mag_sq, freqs, bin_width, is_linear_freqs, freq_step, is_log_freqs, start_freq, stop_freq)
        results["noise_rms_a_weighted"] = rms_a

        return results

    @staticmethod
    def calculate_lockin_measurement(signal, frequency, sampling_rate, phase_ref=0.0, window_name="hann"):
        """
        Performs a single-point Lock-in detection (Coherent Demodulation).
        Returns: magnitude, phase (degrees)
        """
        N = len(signal)

        # Generate Reference Sine/Cosine (Quadrature)
        # We need two orthogonal references to recover Phase and Magnitude independent of alignment
        # Optimization: Use cached reference signals and apply phase rotation
        sin_ref, cos_ref = _get_reference_signals(N, sampling_rate, frequency)

        # Windowing
        # Important if N is not integer number of cycles
        w = get_cached_window(window_name, N)
        w_mean = np.mean(w)

        # Multiply (Mix)
        # Optimization: Use dot product to avoid allocating full mix arrays
        # val = 2 * mean(sig * ref * w) / w_mean
        #     = 2 * sum(sig * w * ref) / N / w_mean
        #     = 2 * dot(sig * w, ref) / (N * w_mean)

        sig_w = signal * w
        scaling = 2.0 / (N * w_mean)

        # Compute dot products with raw reference signals
        # This avoids allocating new mixed reference arrays (ref_sin, ref_cos)
        raw_x = np.dot(sig_w, sin_ref)
        raw_y = np.dot(sig_w, cos_ref)

        if phase_ref != 0.0:
            sin_phi = np.sin(phase_ref)
            cos_phi = np.cos(phase_ref)

            # Apply phase rotation to the scalar results
            # sin(theta + phi) = sin(theta)cos(phi) + cos(theta)sin(phi)
            # val_x corresponds to dot(sig_w, ref_sin)
            val_x = (raw_x * cos_phi + raw_y * sin_phi) * scaling

            # cos(theta + phi) = cos(theta)cos(phi) - sin(theta)sin(phi)
            # val_y corresponds to dot(sig_w, ref_cos)
            val_y = (raw_y * cos_phi - raw_x * sin_phi) * scaling
        else:
            val_x = raw_x * scaling
            val_y = raw_y * scaling

        magnitude = np.sqrt(val_x**2 + val_y**2)
        phase = np.arctan2(val_y, val_x)

        return magnitude, np.degrees(phase)
