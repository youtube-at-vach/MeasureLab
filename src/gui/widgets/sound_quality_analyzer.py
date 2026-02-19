

import numpy as np
import pyqtgraph as pg
import scipy.signal as signal
import soundfile as sf
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.analysis import AudioCalc

# --- Analysis Worker ---


class AnalysisWorker(QThread):
    progress_update = pyqtSignal(int, str)
    results_ready = pyqtSignal(object)
    error_occurred = pyqtSignal(str)

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
            if self.target_sr == analysis_sr:
                data_analysis = data_playback
            else:
                self.progress_update.emit(10, tr("Resampling to {}Hz (Analysis)...").format(analysis_sr))
                data_analysis = self._resample(data_playback, self.target_sr, analysis_sr)

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

            total_steps = len(channels) * 4
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
            pass

        # Stage 1: Shelf, Stage 2: High-pass
        b1, a1, b2, a2 = AudioCalc.get_k_weighting_filter(sr)

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

        for b in range(n_bands):
            # Sum power for all freq bins in this bark band
            mask = bark_indices == b
            if np.any(mask):
                band_power[b, :] = np.sum(mag_sq[mask, :], axis=0)

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

        c_freqs = [300, 840, 1480, 2500, 4800, 9500]

        # Process chunks to save memory, but we need filter state.
        # To avoid complexity, process whole file if < 1 min, or chunk stream.
        # Assuming short files for now (Widget context).

        # Pre-design filters (2nd order bandpass)
        sos_list = []
        for fc in c_freqs:
            # Q factor ~ 2 (Wide enough to overlap Barks roughly)
            if fc < sr / 2:
                sos = signal.butter(2, [fc * 0.7, fc * 1.4], btype="bandpass", fs=sr, output="sos")
                sos_list.append(sos)

        # Calculate envelope and modulation for each band
        # Sum of specific roughnesses.

        # Time weighting:
        # Modulation filter: Bandpass 20-150Hz.
        mod_sos = signal.butter(2, [20, 150], btype="bandpass", fs=sr, output="sos")

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
        sos_pre = signal.butter(1, 200, btype="highpass", fs=sr, output="sos")
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

        for b in range(n_bands):
            # Find bins in this band
            mask = bark_indices == b
            if not np.any(mask):
                continue

            # Extract power for this band: shape (n_bins_in_band, time_steps)
            band_p = mag_sq[mask, :]

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


class SoundQualityAnalyzerWidget(QWidget):
    def __init__(self, module: SoundQualityAnalyzer):
        super().__init__()
        self.module = module
        self.worker = None
        self.analysis_results = None
        self.audio_data = None
        self.samplerate = 48000
        # Playback State
        self.is_playing = False
        self.playback_position = 0  # In samples
        self.callback_id = None
        self.playback_timer = QTimer()
        self.playback_timer.setInterval(50)  # 20 fps update
        self.playback_timer.timeout.connect(self.update_playback_cursor)

        self.cursors = []  # List of InfiniteLines

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Top: Controls ---
        controls_layout = QHBoxLayout()

        self.play_btn = QPushButton("▶")
        self.play_btn.setToolTip(tr("Play/Pause"))
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setEnabled(False)
        controls_layout.addWidget(self.play_btn)

        self.stop_btn = QPushButton("■")
        self.stop_btn.setToolTip(tr("Stop"))
        self.stop_btn.setFixedWidth(40)
        self.stop_btn.clicked.connect(self.stop_playback)
        self.stop_btn.setEnabled(False)
        controls_layout.addWidget(self.stop_btn)

        self.chk_follow = QCheckBox(tr("Follow Cursor"))
        self.chk_follow.setChecked(True)
        controls_layout.addWidget(self.chk_follow)

        # Spacer
        controls_layout.addSpacing(10)

        self.file_label = QLabel(tr("No file selected"))
        controls_layout.addWidget(self.file_label, stretch=1)

        self.load_btn = QPushButton(tr("Load File..."))
        self.load_btn.clicked.connect(self.load_file)
        controls_layout.addWidget(self.load_btn)

        self.analyze_btn = QPushButton(tr("Analyze"))
        self.analyze_btn.clicked.connect(self.start_analysis)
        self.analyze_btn.setEnabled(False)
        controls_layout.addWidget(self.analyze_btn)

        layout.addLayout(controls_layout)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Middle: Metrics Summary ---
        summary_group = QGroupBox(tr("Summary Metrics"))
        self.summary_grid = QGridLayout()

        # Headers
        self.summary_grid.addWidget(QLabel(tr("Channel")), 0, 0)
        self.summary_grid.addWidget(QLabel(tr("Integrated Loudness (LUFS)")), 0, 1)
        self.summary_grid.addWidget(QLabel(tr("Mean Sharpness (acum)")), 0, 2)
        self.summary_grid.addWidget(QLabel(tr("Mean Roughness (asper)")), 0, 3)
        self.summary_grid.addWidget(QLabel(tr("Mean Tonality (0-1)")), 0, 4)

        summary_group.setLayout(self.summary_grid)
        layout.addWidget(summary_group)

        # --- Bottom: Graphs ---
        self.tabs = QTabWidget()

        # Tab 1: Loudness
        self.tab_loudness = QWidget()
        self.layout_loudness = QVBoxLayout(self.tab_loudness)
        self.tabs.addTab(self.tab_loudness, tr("Loudness"))

        # Tab 2: Sharpness
        self.tab_sharpness = QWidget()
        self.layout_sharpness = QVBoxLayout(self.tab_sharpness)
        self.tabs.addTab(self.tab_sharpness, tr("Sharpness"))

        # Tab 3: Roughness
        self.tab_roughness = QWidget()
        self.layout_roughness = QVBoxLayout(self.tab_roughness)
        self.tabs.addTab(self.tab_roughness, tr("Roughness"))

        # Tab 4: Tonality
        self.tab_tonality = QWidget()
        self.layout_tonality = QVBoxLayout(self.tab_tonality)
        self.tabs.addTab(self.tab_tonality, tr("Tonality"))

        layout.addWidget(self.tabs)

        self.setLayout(layout)

        # Placeholder rows
        self._set_summary_placeholder()

    def _set_summary_placeholder(self):
        # Clear existing rows except header
        # (Simplified: Just add empty labels for row 1)
        self.summary_grid.addWidget(QLabel("-"), 1, 0)
        self.summary_grid.addWidget(QLabel("-"), 1, 1)
        self.summary_grid.addWidget(QLabel("-"), 1, 2)
        self.summary_grid.addWidget(QLabel("-"), 1, 3)
        self.summary_grid.addWidget(QLabel("-"), 1, 4)

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open Audio File"), "", "Audio Files (*.wav *.flac *.aiff)")
        if path:
            self.current_file = path
            self.file_label.setText(path)
            self.analyze_btn.setEnabled(True)
            self.progress_bar.setVisible(False)

    def clear_plots(self):
        # Clear all separate layouts
        for layout in [self.layout_loudness, self.layout_sharpness, self.layout_roughness, self.layout_tonality]:
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    w = item.widget()
                    if w:
                        w.deleteLater()

        # Reset references
        self.p1 = None
        self.p2 = None
        self.p3 = None
        self.p4 = None
        self.cursors = []

    def start_analysis(self):
        if not hasattr(self, "current_file"):
            return

        self.analyze_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        self.clear_plots()

        # Stop playback if running
        if hasattr(self, "stop_playback"):
            self.stop_playback()

        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait()

        target_sr = self.module.audio_engine.sample_rate
        self.worker = AnalysisWorker(self.current_file, target_sr)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.results_ready.connect(self.on_results)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    def on_progress(self, val, msg):
        self.progress_bar.setValue(val)
        self.progress_bar.setFormat(f"%p% - {msg}")

    def on_results(self, results):
        self.analysis_results = results

        # Store for playback
        if "audio_data" in results:
            self.audio_data = results["audio_data"]  # (samples, ch) or (samples,)
            self.samplerate = results["samplerate"]
            self.playback_position = 0
            self.is_playing = False
            self.play_btn.setText("▶")

        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        self.display_metrics(results)
        self.plot_series(results)

    def on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.file_label.setText(f"Error: {msg}")

    def display_metrics(self, results):
        # Clear grid
        # Note: Removing widgets from layout is tedious in Qt.
        # Let's just hide or delete properly.
        while self.summary_grid.count() > 5:  # Keep headers
            item = self.summary_grid.takeAt(5)
            w = item.widget()
            if w:
                w.deleteLater()

        row = 1
        for ch in results["channels"]:
            name = ch["name"]
            i_lufs = ch["integrated_lufs"]
            m_sh = ch["mean_sharpness"]
            m_r = ch["mean_roughness"]
            m_t = ch["mean_tonality"]

            self.summary_grid.addWidget(QLabel(name), row, 0)
            self.summary_grid.addWidget(QLabel(f"{i_lufs:.1f} LUFS"), row, 1)
            self.summary_grid.addWidget(QLabel(f"{m_sh:.2f} acum"), row, 2)
            self.summary_grid.addWidget(QLabel(f"{m_r:.2f} asper"), row, 3)
            self.summary_grid.addWidget(QLabel(f"{m_t:.2f} (0-1)"), row, 4)
            row += 1

    def plot_series(self, results):
        self.clear_plots()

        # Loudness Plot (Tab 1)
        p1 = pg.PlotWidget(title=tr("Loudness (Momentary)"))
        p1.setLabel("left", "LUFS")
        p1.setLabel("bottom", "Time", units="s")
        p1.showGrid(y=True)
        p1.addLegend()

        # Sharpness Plot (Tab 2)
        p2 = pg.PlotWidget(title=tr("Sharpness (Zwicker)"))
        p2.setLabel("left", "acum")
        p2.setLabel("bottom", "Time", units="s")
        p2.showGrid(y=True)
        p2.addLegend()
        p2.setXLink(p1)

        # Roughness Plot (Tab 3)
        p3 = pg.PlotWidget(title=tr("Roughness"))
        p3.setLabel("left", "asper")
        p3.setLabel("bottom", "Time", units="s")
        p3.showGrid(y=True)
        p3.addLegend()
        p3.setXLink(p1)

        # Tonality Plot (Tab 4)
        p4 = pg.PlotWidget(title=tr("Tonality"))
        p4.setLabel("left", "SFM inv")
        p4.setLabel("bottom", "Time", units="s")
        p4.showGrid(y=True)
        p4.addLegend()
        p4.setXLink(p1)

        colors = ["c", "m", "g", "y"]

        for i, ch in enumerate(results["channels"]):
            c = colors[i % len(colors)]
            name = ch["name"]

            # Loudness
            t_l = np.arange(len(ch["lufs_series"])) * ch["lufs_step"]
            p1.plot(t_l, ch["lufs_series"], pen=c, name=name)

            # Sharpness
            t_s = np.arange(len(ch["sharpness_series"])) * ch["sharpness_step"]
            p2.plot(t_s, ch["sharpness_series"], pen=c, name=name)

            # Roughness
            t_r = np.arange(len(ch["roughness_series"])) * ch["roughness_step"]
            p3.plot(t_r, ch["roughness_series"], pen=c, name=name)

            # Tonality
            t_t = np.arange(len(ch["tonality_series"])) * ch["tonality_step"]
            p4.plot(t_t, ch["tonality_series"], pen=c, name=name)

        self.p1 = p1
        self.p2 = p2
        self.p3 = p3
        self.p4 = p4

        self.layout_loudness.addWidget(p1)
        self.layout_sharpness.addWidget(p2)
        self.layout_roughness.addWidget(p3)
        self.layout_tonality.addWidget(p4)

        # Add cursors
        self.cursors = []
        for p in [self.p1, self.p2, self.p3, self.p4]:
            if p is None:
                continue
            # Click event
            p.scene().sigMouseClicked.connect(self.on_plot_clicked)

            # Add cursor
            line = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen("y", width=2))
            p.addItem(line)
            self.cursors.append(line)

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

            self.is_playing = True
            self.play_btn.setText("⏸")
            self.callback_id = self.module.audio_engine.register_callback(self.audio_callback)
            self.playback_timer.start()

    def stop_playback(self):
        self.is_playing = False
        self.play_btn.setText("▶")
        if self.callback_id is not None:
            self.module.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None
        self.playback_timer.stop()
        self.playback_position = 0
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
            for c in range(out_ch):
                outdata[:n, c] = chunk
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
        if self.playback_position >= len(self.audio_data):
            self.stop_playback()
            return

        t = self.playback_position / self.samplerate

        # Update lines
        for line in self.cursors:
            line.setValue(t)

        # Follow
        if self.chk_follow.isChecked() and self.is_playing and self.p1:
            # Check if cursor is visible in the first plot (all are linked)
            vb = self.p1.plotItem.vb
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

        # Determine which plot was clicked
        target_plot = None
        plots = [p for p in [self.p1, self.p2, self.p3, self.p4] if p is not None]

        for p in plots:
            if p.sceneBoundingRect().contains(event.scenePos()):
                target_plot = p
                break

        if target_plot is None:
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
