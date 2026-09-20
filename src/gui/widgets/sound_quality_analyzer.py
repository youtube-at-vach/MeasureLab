import functools
import logging
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pyqtgraph as pg
import scipy.signal as signal
import soundfile as sf
from PyQt6.QtCore import QSize, QEvent, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.gui.styles import MONOSPACE_FONT_FAMILY, button_style
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc

logger = logging.getLogger(__name__)

# --- Analysis Worker ---


class AnalysisWorker(QThread):
    progress_update = pyqtSignal(int, str)
    results_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

    @classmethod
    @functools.lru_cache(maxsize=32)
    def _get_sos_filter(cls, filter_type, sr):
        if filter_type == "highpass_200":
            return signal.butter(1, 200, btype="highpass", fs=sr, output="sos")
        elif filter_type == "bandpass_20_150":
            return signal.butter(2, [20, 150], btype="bandpass", fs=sr, output="sos")
        elif filter_type == "bandpass_0_5_20":
            return signal.butter(2, [0.5, 20], btype="bandpass", fs=sr, output="sos")
        raise ValueError(f"Unknown filter type: {filter_type}")

    def __init__(self, file_path, target_sr):
        super().__init__()
        self.file_path = file_path
        self.target_sr = target_sr
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.progress_update.emit(0, tr("Loading file..."))
            valid, msg = AudioCalc.validate_audio_file_size(self.file_path)
            if not valid:
                self.error_occurred.emit(msg)
                return

            data, samplerate = sf.read(self.file_path)

            # 1. Prepare Playback Data (at target_sr, e.g. 44.1k or 48k)
            # This ensures playback speed is correct for the Audio Engine
            if samplerate != self.target_sr:
                self.progress_update.emit(5, tr("Resampling to {}Hz (Playback)...").format(self.target_sr))
                data_playback = self._resample(data, samplerate, self.target_sr)
            else:
                data_playback = data

            # 2. Prepare Analysis Data (at 48kHz)
            # The filters (Loudness K-weighting) and psychoacoustic approximations
            # are tuned for 48kHz.
            analysis_sr = 48000
            # Always derive analysis from the original audio. Going through the
            # playback rate can discard frequency content and make measurements
            # depend on the selected output device.
            if samplerate == analysis_sr:
                data_analysis = data
            elif self.target_sr == analysis_sr:
                data_analysis = data_playback
            else:
                self.progress_update.emit(10, tr("Resampling to {}Hz (Analysis)...").format(analysis_sr))
                data_analysis = self._resample(data, samplerate, analysis_sr)

            if self._is_cancelled:
                return

            # Analyze mono/stereo
            # If stereo -> [L, R]
            if data_analysis.ndim == 1:
                channels = [data_analysis]
                ch_names = ["Mono"]
            else:
                channels = [data_analysis[:, 0], data_analysis[:, 1]]
                ch_names = ["Left", "Right"]

            results = {"samplerate": self.target_sr, "duration": len(data_playback) / self.target_sr, "channels": []}

            total_steps = len(channels) * 6
            current_step = 0

            for i, audio in enumerate(channels):
                ch_res = {"name": ch_names[i]}

                # 1. Loudness
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100), tr("Calculating Loudness ({})...").format(ch_names[i])
                )
                l_res = self._calc_loudness(audio, analysis_sr)
                ch_res.update(l_res)
                current_step += 1

                # 2. Sharpness
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100), tr("Calculating Sharpness ({})...").format(ch_names[i])
                )
                s_res = self._calc_sharpness(audio, analysis_sr)
                ch_res.update(s_res)
                current_step += 1

                # 3. Roughness
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100), tr("Calculating Roughness ({})...").format(ch_names[i])
                )
                r_res = self._calc_roughness(audio, analysis_sr)
                ch_res.update(r_res)
                current_step += 1

                # 4. Tonality
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100), tr("Calculating Tonality ({})...").format(ch_names[i])
                )
                t_res = self._calc_tonality(audio, analysis_sr)
                ch_res.update(t_res)
                current_step += 1

                # 5. Fluctuation Strength
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100),
                    tr("Calculating Fluctuation Strength ({})...").format(ch_names[i]),
                )
                f_res = self._calc_fluctuation_strength(audio, analysis_sr)
                ch_res.update(f_res)
                current_step += 1

                # 6. Articulation Index
                if self._is_cancelled:
                    return
                self.progress_update.emit(
                    int((current_step / total_steps) * 100),
                    tr("Calculating Articulation Index ({})...").format(ch_names[i]),
                )
                a_res = self._calc_articulation_index(audio, analysis_sr)
                ch_res.update(a_res)
                current_step += 1

                results["channels"].append(ch_res)

            # Add raw audio for playback
            # Store as float32 for audio engine
            results["audio_data"] = data_playback.astype(np.float32)
            results["samplerate"] = self.target_sr  # Engine rate

            self.results_ready.emit(results)

        except Exception as e:
            import traceback

            traceback.print_exc()
            self.error_occurred.emit(str(e))

    def _resample(self, data, src_sr, target_sr):
        """
        High-quality resampling using polyphase filtering (scipy.signal.resample_poly).
        """
        if src_sr == target_sr:
            return data

        # Calculate greatest common divisor to find rational approximate
        # But resample_poly takes up/down.
        # e.g. 44100 -> 48000 : up=160, down=147
        # e.g. 48000 -> 44100 : up=147, down=160
        import math

        g = math.gcd(target_sr, src_sr)
        up = target_sr // g
        down = src_sr // g

        # If factors are too large, fallback to FFT resampling or similar?
        # resample_poly is efficient but large factors can be slow.
        # Limit window size if needed, but usually fine for standard rates.

        if data.ndim == 1:
            return signal.resample_poly(data, up, down)
        else:
            return signal.resample_poly(data, up, down, axis=0)

    def _calc_loudness(self, audio, sr):
        # Time-series (Momentary)
        # Sliding window 400ms, overlap 75% -> step 100ms
        window_sec = 0.4
        step_sec = 0.1

        # K-weighting filters (BS.1770) - Designed for 48kHz
        # Since we adhere to Resampling before analysis, sr IS 48000.
        if abs(sr - 48000) > 10:
            # Fallback warning or attempt to design filter
            logger.warning(
                "K-weighting filters are designed for 48kHz, but input is %.1fHz. Results may be inaccurate.", sr
            )

        # Stage 1: Shelf
        b1 = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
        a1 = np.array([1.0, -1.69065929318241, 0.73248077421585])
        # Stage 2: High-pass
        b2 = np.array([1.0, -2.0, 1.0])
        a2 = np.array([1.0, -1.99004745483398, 0.99007225036621])

        y = signal.lfilter(b1, a1, audio)
        y = signal.lfilter(b2, a2, y)

        # Power
        p = y**2

        # Block processing
        block_size = int(window_sec * sr)
        step_size = int(step_sec * sr)

        kernel = np.ones(block_size) / block_size
        p_smoothed = signal.fftconvolve(p, kernel, mode="valid")

        # Downsample to step size
        p_blocks = p_smoothed[::step_size]

        # Momentary LUFS series
        m_lufs = -0.691 + 10 * np.log10(p_blocks + 1e-10)
        m_lufs[m_lufs <= -100] = -100.0

        # Integrated
        abs_gate = -70.0
        rel_gate_threshold = -10.0

        g1 = p_blocks[m_lufs > abs_gate]
        if len(g1) == 0:
            return {"integrated_lufs": -100.0, "lufs_series": m_lufs, "lufs_step": step_sec}

        z_avg_gated = np.mean(g1)
        gamma_a = -0.691 + 10 * np.log10(z_avg_gated)

        rel_gate = gamma_a + rel_gate_threshold
        g2 = p_blocks[m_lufs > rel_gate]

        if len(g2) == 0:
            return {"integrated_lufs": -100.0, "lufs_series": m_lufs, "lufs_step": step_sec}

        z_avg_final = np.mean(g2)
        integrated = -0.691 + 10 * np.log10(z_avg_final)

        return {"integrated_lufs": integrated, "lufs_series": m_lufs, "lufs_step": step_sec}

    def _calc_sharpness(self, audio, sr):
        # Zwicker Sharpness
        # S = 0.11 * Integral(N' * g(z) * z * dz) / Integral(N' * dz)

        window_sec = 0.4  # Consistent with others
        step_sec = 0.1
        nperseg = int(window_sec * sr)
        noverlap = int(nperseg - (step_sec * sr))

        # STFT
        f, t, Zxx = signal.stft(audio, fs=sr, window="hann", nperseg=nperseg, noverlap=noverlap)
        mag_sq = np.abs(Zxx) ** 2

        # 24 Critical Bands (Bark scale)
        # Bark center frequencies (approx)
        # We integrate power in each bark band

        # Bark conversion function
        # z = 13*atan(0.00076*f) + 3.5*atan((f/7500)^2)
        barks_f = 13 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500) ** 2)

        # Divide into 0.5 Bark steps? Or 1.0 Bark integer bands?
        # Zwicker usually uses 24 bands.

        n_bands = 24
        band_power = np.zeros((n_bands, Zxx.shape[1]))

        # Vectorized binning
        # Map each freq bin to a bark band index (0..23)
        # Use floor to bin
        bark_indices = np.floor(barks_f).astype(int)

        # Vectorized accumulation using contiguous slicing (barks_f is monotonically increasing)
        bounds = np.searchsorted(bark_indices, np.arange(n_bands + 1))

        for b in range(n_bands):
            start, end = bounds[b], bounds[b + 1]
            if start < end:
                # Sum power for all freq bins in this bark band
                band_power[b, :] = np.sum(mag_sq[start:end, :], axis=0)

        # Specific Loudness N' approx: E^0.23
        # Ideally should spread excitation, but this is simplified "core" loudness
        specific_loudness = band_power**0.23

        # Total Loudness N = Sum(N') * dz (dz=1 Bark)
        total_loudness = np.sum(specific_loudness, axis=0)

        # Weighting function g(z)
        # g(z) = 1 for z < 15.8
        # g(z) = 0.15 * exp(0.42 * (z - 15.8)) + 0.85  (Typical Fastl approx)
        # Let's precompute g for band centers z = i + 0.5
        z_vals = np.arange(n_bands) + 0.5
        g_vals = np.ones(n_bands)
        mask_high = z_vals >= 15.8
        g_vals[mask_high] = 0.15 * np.exp(0.42 * (z_vals[mask_high] - 15.8)) + 0.85

        # Calculate Moment
        # sum( N'(z) * g(z) * z * dz )
        # broadcasting: (24, T) * (24,) * (24,)
        weighted_moment = np.sum(specific_loudness * g_vals[:, np.newaxis] * z_vals[:, np.newaxis], axis=0)

        # Sharpness S
        # Avoid div by zero
        S = np.zeros_like(total_loudness)
        valid = total_loudness > 1e-9
        S[valid] = 0.11 * weighted_moment[valid] / total_loudness[valid]

        return {"mean_sharpness": np.mean(S), "sharpness_series": S, "sharpness_step": step_sec}

    def _calc_roughness(self, audio, sr):
        # Multi-band Roughness (Simplified Daniel & Weber)
        # 1. Split into critical bands (simulated by processing STFT bins or simple bandpass? STFT is easier here for Python)
        #    Actually, for modulation extraction, we need time-domain envelopes.
        #    STFT frames are too slow/aliased for <70Hz modulation resolution if hop is large.
        #    Bandpass Filters + Hilbert is better.

        # To keep it efficient:
        # Select representative center frequencies (Bark centers).
        # e.g. 1 Bark steps -> 24 filters. Expensive.
        # Reduced set: 2, 4, 8, 12, 16, 20 Bark? (Low to High)
        # Or standard 47 channels? Too many.
        # Let's use 5 broad bands for "rough estimate": Bass, Low-Mid, Mid, High-Mid, High.
        # Or just stick to the single broadband modulation if CPU is concern?
        # User wants "Functional completion".

        # Let's try a 4-band split to capture frequency dependence.
        # Bands: <300Hz, 300-2400Hz, 2400-9600Hz, >9600Hz ?
        # Roughness is dominant in mid frequencies.

        # Let's use `scipy.signal.sosfilt` with a few Bark filters.
        # Center freqs for Barks 3, 7, 11, 15, 19 (~ 300, 840, 1480, 2500, 4800 Hz)

        # Process chunks to save memory, but we need filter state.
        # To avoid complexity, process whole file if < 1 min, or chunk stream.
        # Assuming short files for now (Widget context).

        # Calculate envelope and modulation for each band
        # Sum of specific roughnesses.

        # Time weighting:
        # Modulation filter: Bandpass 20-150Hz.
        mod_sos = self._get_sos_filter("bandpass_20_150", sr)

        # We need time series output, so we compute R(t)
        # This is getting heavy.
        # Let's go back to single-band or simplified approach BUT with correct weighting.
        # Daniel & Weber: R ~ f_mod * m * ...

        # Simplified "Single-Channel" improved:
        # 1. Filter to "sensitive region" (e.g. 1kHz +- bandwidth).
        # Actually roughness comes from beating adjacent partials ANYWHERE.
        # Broadband envelope captures "global" roughness (e.g. AM at 70Hz).

        # Let's stick thereto for performance but improve the weighting.

        # 1. Hilbert Envelope of full signal (or filtered to 200Hz-15kHz)
        # Remove DC/Sub-bass which dominates envelope but doesn't cause roughness.
        sos_pre = self._get_sos_filter("highpass_200", sr)
        filtered = signal.sosfilt(sos_pre, audio)

        env = np.abs(signal.hilbert(filtered))
        env_ac = env - np.mean(env)

        # 2. Extract Modulation Signal (20-150 Hz)
        mod_signal = signal.sosfilt(mod_sos, env_ac)

        # 3. RMS Calculation of Modulation vs Carrier
        # Moving RMS
        window_sec = 0.4
        step_sec = 0.1
        block_size = int(window_sec * sr)
        step_size = int(step_sec * sr)

        # Use simple block iteration
        r_series = []

        # Pre-calc squared for RMS
        mod_sq = mod_signal**2
        car_sq = filtered**2  # Carrier power reference

        kernel = np.ones(block_size) / block_size
        mod_rms = np.sqrt(signal.fftconvolve(mod_sq, kernel, mode="valid"))
        car_rms = np.sqrt(signal.fftconvolve(car_sq, kernel, mode="valid"))

        # Downsample
        mod_rms = mod_rms[::step_size]
        car_rms = car_rms[::step_size]

        # Modulation Index m = mod / car
        # Roughness ~ m (referenced to 100% mod at 1kHz.
        # Our logic gives m=1 for 100% mod.
        # So R ~ m (approx).

        # Avoid div zero
        with np.errstate(divide="ignore", invalid="ignore"):
            m = mod_rms / (car_rms + 1e-9)
            m[car_rms < 1e-4] = 0

        # Calibration (Approximation)
        # 1 asper ~ 100% mod at 1kHz.
        # Our logic gives m=1 for 100% mod.
        # So R ~ m (approx).
        r_series = m

        return {"mean_roughness": np.mean(r_series), "roughness_series": r_series, "roughness_step": step_sec}

    def _calc_tonality(self, audio, sr):
        # Tonality via Spectral Flatness Measure (SFM)
        # Improved: Per-band SFM (Bark scale) to handle spectral tilt and silence.

        window_sec = 0.2
        nperseg = int(window_sec * sr)
        noverlap = int(nperseg // 2)

        # STFT
        f, t, Zxx = signal.stft(audio, fs=sr, window="hann", nperseg=nperseg, noverlap=noverlap)
        mag_sq = np.abs(Zxx) ** 2 + 1e-12  # Power

        # Define Critical Bands (Bark scale approx)
        # Using a simplified 24-band mapping
        # Bark = 13*atan(0.00076*f) + 3.5*atan((f/7500)^2)
        barks_f = 13 * np.arctan(0.00076 * f) + 3.5 * np.arctan((f / 7500) ** 2)
        bark_indices = np.floor(barks_f).astype(int)

        n_bands = 24

        # Accumulators for weighted average
        weighted_tonality_sum = np.zeros(Zxx.shape[1])
        total_weight = np.zeros(Zxx.shape[1])

        # Vectorized accumulation using contiguous slicing (barks_f is monotonically increasing)
        bounds = np.searchsorted(bark_indices, np.arange(n_bands + 1))

        for b in range(n_bands):
            start, end = bounds[b], bounds[b + 1]
            if start >= end:
                continue

            # Extract power for this band: shape (n_bins_in_band, time_steps)
            band_p = mag_sq[start:end, :]

            # Geometric Mean of this band
            # exp(mean(log(x)))
            geo_mean = np.exp(np.mean(np.log(band_p), axis=0))

            # Arithmetic Mean of this band
            ari_mean = np.mean(band_p, axis=0)

            # SFM for this band
            # Limit SFM to 1.0
            sfm_b = geo_mean / (ari_mean + 1e-12)

            # Band Tonality
            # t_b = 1 - sfm
            t_b = 1.0 - sfm_b
            t_b = np.clip(t_b, 0.0, 1.0)

            # Weighting: Use Total Power in this band
            # Loud bands contribute more to tonality perception.
            # Silent bands (noise floor) will have tiny weight.
            w_b = np.sum(band_p, axis=0)

            # Weighting by loudness (N') might be better conceptually, but Power is a good proxy here.

            weighted_tonality_sum += t_b * w_b
            total_weight += w_b

        # Global Tonality
        # Avoid div by zero
        global_tonality = np.zeros_like(total_weight)
        valid = total_weight > 1e-12
        global_tonality[valid] = weighted_tonality_sum[valid] / total_weight[valid]

        # Calibration:
        # Raw SFM on short frames yields ~0.45 Tonality for White Noise.
        # We rescale so that Noise floor -> 0.0.
        # T_final = (T_raw - 0.45) / 0.55
        global_tonality = (global_tonality - 0.45) / 0.55
        global_tonality = np.clip(global_tonality, 0, 1)

        step = (nperseg - noverlap) / sr

        return {"mean_tonality": np.mean(global_tonality), "tonality_series": global_tonality, "tonality_step": step}

    def _calc_fluctuation_strength(self, audio, sr):
        # Fluctuation Strength (vacil)
        # Similar to roughness but for slower modulations (< 20Hz, peak around 4Hz)

        # 1. Hilbert Envelope of full signal
        sos_pre = self._get_sos_filter("highpass_200", sr)
        filtered = signal.sosfilt(sos_pre, audio)

        env = np.abs(signal.hilbert(filtered))
        env_ac = env - np.mean(env)

        # 2. Extract Modulation Signal (0.5-20 Hz)
        mod_sos = self._get_sos_filter("bandpass_0_5_20", sr)
        mod_signal = signal.sosfilt(mod_sos, env_ac)

        # 3. RMS Calculation of Modulation vs Carrier
        window_sec = 0.4
        step_sec = 0.1
        block_size = int(window_sec * sr)
        step_size = int(step_sec * sr)

        mod_sq = mod_signal**2
        car_sq = filtered**2

        kernel = np.ones(block_size) / block_size
        mod_rms = np.sqrt(signal.fftconvolve(mod_sq, kernel, mode="valid"))
        car_rms = np.sqrt(signal.fftconvolve(car_sq, kernel, mode="valid"))

        mod_rms = mod_rms[::step_size]
        car_rms = car_rms[::step_size]

        with np.errstate(divide="ignore", invalid="ignore"):
            m = mod_rms / (car_rms + 1e-9)
            m[car_rms < 1e-4] = 0

        # Approximation: roughly similar modulation index scale
        f_series = m

        return {"mean_fluctuation": np.mean(f_series), "fluctuation_series": f_series, "fluctuation_step": step_sec}

    def _calc_articulation_index(self, audio, sr):
        # Articulation Index (AI)
        # 15 bands from 200 Hz to 5000 Hz, applying fixed weights to S/N ratio.

        window_sec = 0.2
        nperseg = int(window_sec * sr)
        noverlap = int(nperseg // 2)

        f, t, Zxx = signal.stft(audio, fs=sr, window="hann", nperseg=nperseg, noverlap=noverlap)
        mag_sq = np.abs(Zxx) ** 2 + 1e-12

        # 1/3 Octave ISO center bands relevant to speech
        center_freqs = [200, 250, 315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000]
        # French-Steinberg approx weights
        weights = [
            0.012,
            0.030,
            0.030,
            0.042,
            0.042,
            0.060,
            0.060,
            0.072,
            0.090,
            0.111,
            0.111,
            0.104,
            0.082,
            0.070,
            0.054,
        ]
        weights = np.array(weights)

        # Band boundaries
        factor = 2 ** (1 / 6)
        lower_edges = [fc / factor for fc in center_freqs]
        upper_edges = [fc * factor for fc in center_freqs]

        ai_series = np.zeros(Zxx.shape[1])
        noise_floor_db = -60.0  # Assumed nominal noise

        band_levels = []
        for low, high in zip(lower_edges, upper_edges, strict=True):
            mask = (f >= low) & (f <= high)
            if np.any(mask):
                band_p = np.sum(mag_sq[mask, :], axis=0)
                band_db = 10 * np.log10(band_p + 1e-12)
            else:
                band_db = np.full(Zxx.shape[1], -100.0)
            band_levels.append(band_db)

        # Calculate AI per time frame
        band_levels_arr = np.array(band_levels)
        snr_clipped = np.clip(band_levels_arr - noise_floor_db, -12, 18)
        contribution = (snr_clipped + 12) / 30.0
        ai_series = weights @ contribution

        ai_series = np.clip(ai_series, 0.0, 1.0)
        step = (nperseg - noverlap) / sr

        return {"mean_ai": np.mean(ai_series), "ai_series": ai_series, "ai_step": step}


# --- Widget ---


class SoundQualityAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

    @property
    def name(self) -> str:
        return "Sound Quality Analyzer"

    @property
    def description(self) -> str:
        return "Offline analysis of sound quality metrics (Loudness, Sharpness, Roughness)."

    def get_widget(self):
        return SoundQualityAnalyzerWidget(self)


@dataclass(frozen=True)
class QualityMetric:
    title: str
    summary: str
    series: str
    unit: str
    precision: int
    method: str


def quality_metrics():
    """One definition drives navigation, readouts, and the history plot."""
    return (
        QualityMetric(
            tr("Loudness"), "integrated_lufs", "lufs", "LUFS", 1, tr("Integrated loudness · Momentary history (400 ms)")
        ),
        QualityMetric(
            tr("Sharpness"), "mean_sharpness", "sharpness", "acum", 2, tr("Mean sharpness · Simplified Zwicker model")
        ),
        QualityMetric(
            tr("Roughness"),
            "mean_roughness",
            "roughness",
            "asper",
            2,
            tr("Mean roughness · Broadband modulation estimate"),
        ),
        QualityMetric(
            tr("Tonality"), "mean_tonality", "tonality", "0–1", 2, tr("Mean tonality · Inverse spectral flatness")
        ),
        QualityMetric(
            tr("Fluctuation Strength"),
            "mean_fluctuation",
            "fluctuation",
            "vacil",
            2,
            tr("Mean fluctuation strength · Slow modulation estimate"),
        ),
        QualityMetric(
            tr("Articulation Index"), "mean_ai", "ai", "0–1", 2, tr("Mean AI · Assumed noise floor: −60 dBFS")
        ),
    )


class MetricCard(QPushButton):
    """A keyboard-accessible metric selector with aligned channel readouts."""

    def __init__(self, metric):
        super().__init__()
        self.metric = metric
        self.setCheckable(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(72)
        self.setToolTip(metric.method)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(3)
        title = QLabel(metric.title)
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.values = [QLabel("—"), QLabel("")]
        for value in self.values:
            value.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 20px;")
            row.addWidget(value)
        unit = QLabel(metric.unit)
        unit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        unit.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        row.addWidget(unit)
        layout.addLayout(row)
        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("""
            MetricCard { background: palette(base); border: 1px solid palette(mid);
                         border-radius: 6px; text-align: left; }
            MetricCard:hover { border-color: palette(link); }
            MetricCard:checked { background: palette(alternate-base); border: 2px solid palette(highlight); }
            MetricCard:focus { border: 2px solid palette(link); }
            MetricCard QLabel { background: transparent; border: none; }
        """)
        self.setAccessibleName(metric.title)

    def sizeHint(self):
        return self.layout().sizeHint().expandedTo(QSize(240, 76))

    def minimumSizeHint(self):
        return self.layout().minimumSize().expandedTo(QSize(0, 76))

    def set_channels(self, channels, colors):
        descriptions = []
        for i, label in enumerate(self.values):
            if i < len(channels):
                channel = channels[i]
                value = channel.get(self.metric.summary, np.nan)
                text = f"{value:.{self.metric.precision}f}" if np.isfinite(value) else "—"
                label.setText(text)
                label.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY}; font-size: 20px; color: {colors[i]};")
                descriptions.append(f"{tr(channel['name'])}: {text} {self.metric.unit}")
            else:
                label.setText("—" if i == 0 else "")
        self.setAccessibleName(f"{self.metric.title}: " + "; ".join(descriptions))


class SoundQualityAnalyzerWidget(QWidget):
    def __init__(self, module: SoundQualityAnalyzer):
        super().__init__()
        self.module = module
        self.worker = None
        self.analysis_results = None
        self.audio_data = None
        self.samplerate = 48000
        self.is_playing = False
        self.playback_position = 0
        self.callback_id = None
        self._analyzing = False
        self._cancel_requested = False
        self.metrics = quality_metrics()
        self.selected_metric = 0
        self.plot = None
        self.cursors = []
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(50)
        self.playback_timer.timeout.connect(self.update_playback_cursor)
        self.init_ui()

    def init_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)
        source = QHBoxLayout()
        source.setSpacing(10)
        file_info = QVBoxLayout()
        self.file_label = QLabel(tr("No file selected"))
        self.file_label.setTextFormat(Qt.TextFormat.PlainText)
        self.file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.file_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.file_details = QLabel(tr("Open an audio file to measure its sound quality."))
        self.file_details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.file_details.setStyleSheet("color: palette(placeholder-text);")
        file_info.addWidget(self.file_label)
        file_info.addWidget(self.file_details)
        source.addLayout(file_info, 1)
        self.load_btn = QPushButton(tr("Load File..."))
        self.load_btn.clicked.connect(self.load_file)
        self.analyze_btn = QPushButton(tr("Analyze"))
        self.analyze_btn.setStyleSheet(button_style("primary", extra="padding: 7px 16px;"))
        self.analyze_btn.clicked.connect(self.start_analysis)
        self.analyze_btn.setEnabled(False)
        self.export_btn = QPushButton(tr("Export CSV..."))
        self.export_btn.clicked.connect(self.export_csv)
        self.export_btn.setEnabled(False)
        for button in (self.load_btn, self.analyze_btn, self.export_btn):
            button.setMinimumHeight(34)
            source.addWidget(button)
        main.addLayout(source)

        status_row = QHBoxLayout()
        self.status_label = QLabel(tr("No file selected"))
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(140)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.hide()
        status_row.addWidget(self.progress_bar)
        self.cancel_btn = QPushButton(tr("Cancel"))
        self.cancel_btn.clicked.connect(self.cancel_analysis)
        self.cancel_btn.hide()
        status_row.addWidget(self.cancel_btn)
        main.addLayout(status_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        overview = QWidget()
        overview.setMinimumWidth(240)
        overview.setMaximumWidth(340)
        overview_layout = QVBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(7)
        summary_heading = QLabel(tr("Summary Metrics"))
        summary_heading.setStyleSheet("font-weight: 600;")
        overview_layout.addWidget(summary_heading)
        self.channel_key = QLabel(tr("Integrated / Mean"))
        self.channel_key.setStyleSheet("color: palette(placeholder-text);")
        overview_layout.addWidget(self.channel_key)
        card_content = QWidget()
        card_layout = QVBoxLayout(card_content)
        card_layout.setContentsMargins(0, 0, 3, 0)
        card_layout.setSpacing(7)
        self.metric_group = QButtonGroup(self)
        self.metric_cards = []
        for i, metric in enumerate(self.metrics):
            card = MetricCard(metric)
            self.metric_group.addButton(card, i)
            self.metric_cards.append(card)
            card_layout.addWidget(card)
        card_layout.addStretch()
        self.metric_cards[0].setChecked(True)
        self.metric_group.idClicked.connect(self.select_metric)
        scroll = QScrollArea()
        scroll.setObjectName("soundQualityMetrics")
        scroll.setProperty("measurelabScrollRole", "dynamic-content")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card_content)
        overview_layout.addWidget(scroll, 1)
        body.addWidget(overview, 3)

        detail = QVBoxLayout()
        detail.setSpacing(8)
        heading = QHBoxLayout()
        self.plot_title = QLabel(self.metrics[0].title)
        self.plot_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        heading.addWidget(self.plot_title, 1)
        self.fit_btn = QPushButton(tr("Fit to data"))
        self.fit_btn.clicked.connect(self.fit_plot)
        self.fit_btn.setEnabled(False)
        heading.addWidget(self.fit_btn)
        detail.addLayout(heading)
        self.method_label = QLabel(self.metrics[0].method)
        self.method_label.setWordWrap(True)
        self.method_label.setStyleSheet("color: palette(placeholder-text);")
        detail.addWidget(self.method_label)
        self.plot_stack = QStackedWidget()
        self.empty_label = QLabel(tr("Load a file, then select Analyze.\nAll six metrics will appear here."))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(
            "background: palette(base); color: palette(placeholder-text); border-radius: 6px; padding: 24px;"
        )
        self.plot_stack.addWidget(self.empty_label)
        detail.addWidget(self.plot_stack, 1)
        self.history_hint = QLabel(tr("Click the graph to seek · Drag to pan · Scroll to zoom"))
        self.history_hint.setWordWrap(True)
        self.history_hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        detail.addWidget(self.history_hint)
        body.addLayout(detail, 8)
        main.addLayout(body, 1)

        transport = QHBoxLayout()
        transport.setSpacing(10)
        self.play_btn = QPushButton("▶")
        self.play_btn.setToolTip(tr("Play/Pause"))
        self.play_btn.setAccessibleName(tr("Play/Pause"))
        self.play_btn.clicked.connect(self.toggle_playback)
        self.stop_btn = QPushButton("■")
        self.stop_btn.setToolTip(tr("Stop"))
        self.stop_btn.setAccessibleName(tr("Stop"))
        self.stop_btn.clicked.connect(self.stop_playback)
        for button in (self.play_btn, self.stop_btn):
            button.setFixedSize(40, 32)
            button.setEnabled(False)
            transport.addWidget(button)
        self.time_label = QLabel("0:00.0 / 0:00.0")
        self.time_label.setStyleSheet(f"font-family: {MONOSPACE_FONT_FAMILY};")
        transport.addWidget(self.time_label)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 10000)
        self.seek_slider.setPageStep(500)
        self.seek_slider.setAccessibleName(tr("Playback position"))
        self.seek_slider.setEnabled(False)
        self.seek_slider.valueChanged.connect(self.seek_playback)
        transport.addWidget(self.seek_slider, 1)
        self.chk_follow = QCheckBox(tr("Follow Cursor"))
        self.chk_follow.setChecked(True)
        transport.addWidget(self.chk_follow)
        main.addLayout(transport)

    def channel_colors(self):
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        return ("#73c7ed", "#edb577") if dark else ("#14658c", "#9b5210")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "metric_cards"):
            if self.analysis_results:
                self.display_metrics(self.analysis_results)
            if self.plot is not None:
                self._style_plot()
                self.select_metric(self.selected_metric)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open Audio File"), "", "Audio Files (*.wav *.flac *.aiff)")
        if path:
            self.clear_results()
            self.current_file = path
            self.file_label.setText(Path(path).name)
            self.file_label.setToolTip(path)
            self.file_details.setText(tr("Ready to analyze"))
            self.status_label.setText(tr("Ready to analyze"))
            self.empty_label.setText(tr("Select Analyze to calculate all six metrics."))
            self.analyze_btn.setEnabled(True)
            self.progress_bar.hide()

    def clear_results(self):
        self.stop_playback()
        self.analysis_results = None
        self.audio_data = None
        for button in (self.play_btn, self.stop_btn, self.export_btn, self.fit_btn, self.seek_slider):
            button.setEnabled(False)
        for card in self.metric_cards:
            card.set_channels([], self.channel_colors())
        self.channel_key.setText(tr("Integrated / Mean"))
        self.time_label.setText("0:00.0 / 0:00.0")
        self.clear_plots()

    def clear_plots(self):
        if self.plot is not None:
            self.plot.clear()
        self.cursors = []
        self.plot_stack.setCurrentIndex(0)

    def start_analysis(self):
        if not hasattr(self, "current_file") or self._analyzing:
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.clear_results()
        self._analyzing = True
        self._cancel_requested = False
        self.analyze_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.status_label.setText(tr("Loading file..."))
        self.file_details.setText(tr("Analyzing audio…"))
        self.empty_label.setText(tr("Analyzing audio…"))
        target_sr = self.module.audio_engine.sample_rate
        self.worker = AnalysisWorker(self.current_file, target_sr)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.results_ready.connect(self.on_results)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.start()

    def cancel_analysis(self):
        if self.worker is not None and self._analyzing:
            self._cancel_requested = True
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(tr("Cancelling…"))

    def on_analysis_finished(self):
        self._analyzing = False
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(hasattr(self, "current_file"))
        self.load_btn.setEnabled(True)
        if self._cancel_requested:
            self.file_details.setText(tr("Ready to analyze"))
            self.status_label.setText(tr("Analysis cancelled"))
            self.empty_label.setText(tr("Select Analyze to calculate all six metrics."))

    def on_progress(self, val, msg):
        if not self._cancel_requested:
            self.progress_bar.setValue(val)
            self.status_label.setText(msg)

    def on_results(self, results):
        if self._cancel_requested:
            return
        self.analysis_results = results
        self.audio_data = results.get("audio_data")
        self.samplerate = results["samplerate"]
        self.playback_position = 0
        self.is_playing = False
        self.play_btn.setText("▶")
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        playable = self.audio_data is not None and len(self.audio_data) > 0
        for control in (self.play_btn, self.stop_btn, self.seek_slider):
            control.setEnabled(playable)
        self.export_btn.setEnabled(True)
        self.fit_btn.setEnabled(True)
        self.status_label.setText(tr("Analysis complete"))
        duration = results.get("duration", len(self.audio_data) / self.samplerate if playable else 0)
        self.file_details.setText(
            tr("{duration} s · Analysis: 48 kHz · Playback: {rate} Hz").format(
                duration=f"{duration:.2f}", rate=self.samplerate
            )
        )
        self.display_metrics(results)
        self.plot_series(results)
        self.update_playback_cursor()

    def on_error(self, msg):
        if self._cancel_requested:
            return
        self.clear_results()
        self.progress_bar.hide()
        self.cancel_btn.hide()
        self.analyze_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.file_details.setText(tr("Ready to analyze"))
        self.status_label.setText(tr("Analysis failed: {}").format(msg))
        self.empty_label.setText(tr("Select Analyze to retry, or load another file."))

    def display_metrics(self, results):
        channels = results.get("channels", [])
        colors = self.channel_colors()
        self.channel_key.setText(
            " &nbsp; ".join(
                f'<span style="color:{colors[i]}">● {tr(ch["name"])}</span>' for i, ch in enumerate(channels[:2])
            )
        )
        for card in self.metric_cards:
            card.set_channels(channels, colors)

    def export_csv(self):
        if not self.analysis_results:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export Metrics to CSV"), "sound_quality_metrics.csv", "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        try:
            import csv

            with open(path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow(
                    [
                        "Channel",
                        "Integrated Loudness (LUFS)",
                        "Mean Sharpness (acum)",
                        "Mean Roughness (asper)",
                        "Mean Tonality (0-1)",
                        "Mean Fluctuation (vacil)",
                        "Mean AI (0-1)",
                    ]
                )

                # Write data rows
                for ch in self.analysis_results.get("channels", []):
                    writer.writerow(
                        [
                            ch["name"],
                            f"{ch['integrated_lufs']:.1f}",
                            f"{ch['mean_sharpness']:.2f}",
                            f"{ch['mean_roughness']:.2f}",
                            f"{ch['mean_tonality']:.2f}",
                            f"{ch['mean_fluctuation']:.2f}",
                            f"{ch['mean_ai']:.2f}",
                        ]
                    )

            QMessageBox.information(
                self, tr("Export Successful"), tr("Successfully exported metrics to:\n{}").format(path)
            )
        except Exception as e:
            QMessageBox.critical(self, tr("Export Failed"), tr("Failed to export metrics.\nError: {}").format(str(e)))

    def plot_series(self, results):
        if self.plot is None:
            self.plot = pg.PlotWidget()
            self.plot.setMinimumSize(240, 180)
            self.plot.showGrid(x=True, y=True, alpha=0.15)
            self.plot.setLabel("bottom", tr("Time"), units="s")
            self.plot.setMenuEnabled(False)
            self.plot.getAxis("left").enableAutoSIPrefix(False)
            self.plot.addLegend(offset=(-12, 12))
            self.plot.scene().sigMouseClicked.connect(self.on_plot_clicked)
            self.plot_stack.addWidget(self.plot)
        self._style_plot()
        self.select_metric(self.selected_metric, preserve_range=False)
        self.plot_stack.setCurrentWidget(self.plot)

    def _style_plot(self):
        palette = self.palette()
        self.plot.setBackground(palette.color(QPalette.ColorRole.Base))
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(palette.color(QPalette.ColorRole.Mid)))
            axis.setTextPen(pg.mkPen(palette.color(QPalette.ColorRole.Text)))
        self.plot.plotItem.legend.setLabelTextColor(palette.color(QPalette.ColorRole.Text))

    def select_metric(self, index, preserve_range=True):
        self.selected_metric = index
        metric = self.metrics[index]
        self.metric_cards[index].setChecked(True)
        self.plot_title.setText(metric.title)
        self.method_label.setText(metric.method)
        if self.plot is None or self.analysis_results is None:
            return
        previous_range = self.plot.viewRange()[0] if preserve_range else None
        self.plot.clear()
        self.plot.setLabel("left", metric.unit)
        for i, channel in enumerate(self.analysis_results["channels"]):
            values = np.asarray(channel.get(metric.series + "_series", []))
            times = np.arange(len(values)) * channel.get(metric.series + "_step", 0.1)
            pen = pg.mkPen(
                self.channel_colors()[i], width=1, style=Qt.PenStyle.SolidLine if i == 0 else Qt.PenStyle.DashLine
            )
            # Dense, antialiased wide/dashed paths are expensive to rasterize.
            # Keep channel styles, but use a one-pixel pen for history traces.
            trace = self.plot.plot(
                times,
                values,
                pen=pen,
                name=tr(channel["name"]),
                connect="finite",
                antialias=False,
            )
            # Enable clipping after attachment, when the ViewBox is available.
            trace.setClipToView(True)
            # History is immutable during playback. Moving the cursor repaints
            # the viewport; reuse the rasterized curves until the view changes.
            # Clipping above also bounds the cache when zooming into long files.
            # Qt invalidates this device-coordinate cache on scale/style changes.
            trace.curve.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        cursor = pg.InfiniteLine(
            pos=self.playback_position / self.samplerate,
            angle=90,
            pen=pg.mkPen(self.palette().color(QPalette.ColorRole.Text), width=1),
        )
        self.plot.addItem(cursor, ignoreBounds=True)
        self.cursors = [cursor]
        self.plot.enableAutoRange(axis="y")
        if previous_range:
            self.plot.setXRange(*previous_range, padding=0)
        else:
            self.fit_plot()

    def fit_plot(self):
        if self.plot is not None and self.analysis_results is not None:
            duration = self.analysis_results.get("duration", 0)
            if not duration and self.audio_data is not None:
                duration = len(self.audio_data) / self.samplerate
            self.plot.setXRange(0, max(duration, 0.1), padding=0.01)
            self.plot.enableAutoRange(axis="y")

    @staticmethod
    def _time_text(seconds):
        minutes, tenths = divmod(max(0, round(seconds * 10)), 600)
        return f"{minutes}:{tenths // 10:02d}.{tenths % 10}"

    def seek_playback(self, value):
        if self.audio_data is None:
            return
        self.playback_position = min(round(value / 10000 * len(self.audio_data)), len(self.audio_data))
        self.update_playback_cursor()

    # --- Playback Logic ---

    def toggle_playback(self):
        if not hasattr(self, "audio_data") or self.audio_data is None:
            return

        if self.is_playing:
            # Pause
            self.is_playing = False
            self.play_btn.setText("▶")
            if self.callback_id is not None:
                self.module.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.playback_timer.stop()
        else:
            # Play
            # Check end
            if self.playback_position >= len(self.audio_data):
                self.playback_position = 0

            try:
                self.callback_id = self.module.audio_engine.register_callback(self.audio_callback)
            except Exception as exc:
                self.status_label.setText(tr("Playback failed: {}").format(exc))
                return
            self.is_playing = True
            self.status_label.setText(tr("Analysis complete"))
            self.play_btn.setText("⏸")
            self.playback_timer.start()

    def stop_playback(self):
        self.is_playing = False
        self.play_btn.setText("▶")
        if self.callback_id is not None:
            self.module.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        self.playback_timer.stop()
        self.playback_position = 0
        self.seek_slider.setValue(0)
        self.update_playback_cursor()

    def audio_callback(self, indata, outdata, frames, time, status):
        if not self.is_playing or self.audio_data is None:
            outdata.fill(0)
            return

        # Write to outdata
        # audio_data can be mono (N,) or stereo (N, 2)
        # outdata is (frames, 2) usually (depending on engine config, but we target stereo)

        remaining = len(self.audio_data) - self.playback_position
        if remaining <= 0:
            outdata.fill(0)
            # Stop? Can't call GUI from thread easily.
            # handled by timer check or just silence until timer stops it?
            # ideally we just signal stop.
            return

        n = min(frames, remaining)

        chunk = self.audio_data[self.playback_position : self.playback_position + n]

        # Map to output
        # outdata shape is (frames, output_channels)
        out_ch = outdata.shape[1]

        if chunk.ndim == 1:
            # Mono to all ch
            outdata[:n, :] = chunk[:, np.newaxis]
        else:
            # Stereo input
            in_ch = chunk.shape[1]
            if in_ch >= out_ch:
                outdata[:n, :] = chunk[:, :out_ch]
            else:
                outdata[:n, :in_ch] = chunk
                # Fill rest with 0 or copy? 0 is safer.
                outdata[:n, in_ch:] = 0

        if n < frames:
            outdata[n:, :] = 0

        self.playback_position += n

    def update_playback_cursor(self):
        if self.audio_data is None:
            return

        # Check if finished
        if self.is_playing and self.playback_position >= len(self.audio_data):
            self.toggle_playback()

        t = self.playback_position / self.samplerate
        duration = len(self.audio_data) / self.samplerate
        self.time_label.setText(f"{self._time_text(t)} / {self._time_text(duration)}")
        self.seek_slider.blockSignals(True)
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(round(t / duration * 10000) if duration else 0)
        self.seek_slider.blockSignals(False)

        # Update lines
        for line in self.cursors:
            line.setValue(t)

        # Follow
        if self.chk_follow.isChecked() and self.is_playing and self.plot is not None:
            # Keep the playback position visible without changing the zoom.
            vb = self.plot.plotItem.vb
            view_range = vb.viewRange()[0]  # x range (min, max)

            # Define margin (e.g. 5%)
            width = view_range[1] - view_range[0]
            margin = width * 0.05

            if t > view_range[1] - margin:
                # Shift view
                vb.setXRange(t - margin, t + width - margin, padding=0)

            elif t < view_range[0]:
                # Should not happen on playback, but maybe seeked back
                vb.setXRange(t - margin, t + width - margin, padding=0)

    def on_plot_clicked(self, event):
        if self.audio_data is None:
            return

        if event.button() != Qt.MouseButton.LeftButton or self.plot is None:
            return
        target_plot = self.plot
        if not target_plot.plotItem.vb.sceneBoundingRect().contains(event.scenePos()):
            return

        # Map scene pos to view pos for the target plot
        pos = target_plot.plotItem.vb.mapSceneToView(event.scenePos())
        t = pos.x()

        if t < 0:
            t = 0
        max_t = len(self.audio_data) / self.samplerate
        if t > max_t:
            t = max_t

        self.playback_position = int(t * self.samplerate)
        self.update_playback_cursor()

    def closeEvent(self, event):
        """Cleanup on close."""
        self.stop_playback()
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()
        super().closeEvent(event)
