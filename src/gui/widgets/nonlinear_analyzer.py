import logging
import threading
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)
from scipy.signal import (
    chirp as signal_chirp,
    fftconvolve,
    savgol_filter,
    butter,
    sosfilt,
)

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.nonlinear_analyzer_core import (
    generate_sss_and_inverse,
    process_amplitude_responses,
    deconvolve_signal,
    find_subsample_peak,
    apply_fractional_delay,
    sinc_resample,
)

logger = logging.getLogger(__name__)


class NonlinearAnalyzerSignals(QObject):
    update_plot = pyqtSignal(object, dict, dict)  # freqs, magnitudes_db_dict, phases_deg_dict
    update_kernels = pyqtSignal(object, list)  # time_ms, list of kernels [h1, h2, h3, h4, h5]
    sweep_finished = pyqtSignal()
    progress = pyqtSignal(int)
    latency_result = pyqtSignal(float)
    error = pyqtSignal(str)


class PlayRecSession:
    """Helper to run a synchronous play/record session via AudioEngine."""

    def __init__(self, audio_engine, output_data, input_channels=2):
        self.audio_engine = audio_engine
        self.output_data = output_data
        self.total_frames = len(output_data)
        self.input_channels = input_channels
        self.input_data = np.zeros((self.total_frames, input_channels), dtype=np.float32)
        self.current_frame = 0
        self.is_complete = False
        self.callback_id = None
        self.lock = threading.Lock()
        self.completion_event = threading.Event()
        self.error = None

    def start(self):
        self.callback_id = self.audio_engine.register_callback(self._callback)
        if self.audio_engine.stream is None and not getattr(self.audio_engine, "offline_mode", False):
            self.error = tr("Audio stream failed to start. Please check audio device settings.")
            self.is_complete = True
            self.completion_event.set()

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        completed = self.completion_event.wait(timeout)
        if not completed:
            self.error = tr("Audio playback timed out. Audio device may have stopped responding.")
        if self.error:
            raise RuntimeError(str(self.error))

    def _callback(self, indata, outdata, frames, time, status):
        with self.lock:
            if self.is_complete:
                outdata.fill(0)
                return

            try:
                remaining = self.total_frames - self.current_frame
                chunk = min(frames, remaining)

                # Playback
                ch_out = min(outdata.shape[1], self.output_data.shape[1])
                outdata[:chunk, :ch_out] = self.output_data[self.current_frame : self.current_frame + chunk, :ch_out]
                if ch_out < outdata.shape[1]:
                    outdata[:chunk, ch_out:] = 0
                if chunk < frames:
                    outdata[chunk:, :] = 0

                # Record
                if indata.shape[1] > 0:
                    ch_to_copy = min(self.input_channels, indata.shape[1])
                    self.input_data[self.current_frame : self.current_frame + chunk, :ch_to_copy] = indata[
                        :chunk, :ch_to_copy
                    ]

                self.current_frame += chunk

                if self.current_frame >= self.total_frames:
                    self.is_complete = True
                    self.completion_event.set()
            except Exception as e:
                self.error = f"Audio Callback Error: {e}"
                self.is_complete = True
                self.completion_event.set()


class NonlinearSweepWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer
        self.is_running = True

    def run(self):
        try:
            self.analyzer._execute_measurement(self)
        except Exception as e:
            logger.error("NonlinearSweepWorker Error: %s", e, exc_info=True)
            self.analyzer.signals.error.emit(str(e))
        finally:
            self.analyzer.signals.sweep_finished.emit()

    def stop(self):
        self.is_running = False


class LatencyCalWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer

    def run(self):
        try:
            self.analyzer.calibrate_latency()
        except Exception as e:
            self.analyzer.signals.error.emit(str(e))


class NonlinearAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.signals = NonlinearAnalyzerSignals()

        # Sweep Parameters
        self.start_freq = 20.0
        self.end_freq = 20000.0
        self.sweep_duration = 5.0  # seconds (Optimized for minimizing phase errors on UAC-232)
        self.amplitude_db = -6.0  # dBFS (peak)
        self.averages = 3  # TSA (Time Synchronized Averaging) count
        self.num_amplitudes = 5  # Number of amplitude steps for PHM (typically 5 to 7 steps)
        self.latency_sec = 0.0
        self.measure_noise_floor = True
        self.measured_noise_floor_dbfs = None

        # Routing Config
        self.output_channel = "STEREO"  # 'L', 'R', 'STEREO'
        self.input_mode = "XFER_REV"  # 'L' (Single Ch), 'XFER' (2-Ch relative)
        self.ref_channel_index = 1
        self.meas_channel_index = 0

        self.worker = None
        self.cal_worker = None
        self._dummy_callback_id = None
        self.signals.sweep_finished.connect(self._cleanup_dummy_callback)
        self.warnings = []

    @property
    def name(self) -> str:
        return "Nonlinear Analyzer"

    @property
    def description(self) -> str:
        return "Extracts true linear response and 2nd-5th harmonics using SSS and Parallel Hammerstein modeling."

    def get_widget(self):
        return NonlinearAnalyzerWidget(self)

    def _dummy_callback(self, indata, outdata, frames, time, status):
        pass

    @property
    def tr(self):
        return tr

    def _cleanup_dummy_callback(self):
        if self._dummy_callback_id is not None:
            self.audio_engine.unregister_callback(self._dummy_callback_id)
            self._dummy_callback_id = None

    def run_play_rec(self, output_data, input_channels=2, progress_callback=None, check_cancelled=None):
        import time

        session = PlayRecSession(self.audio_engine, output_data, input_channels)
        session.start()
        expected_duration = len(output_data) / self.audio_engine.sample_rate
        start_time = time.time()

        while not session.is_complete:
            if check_cancelled and check_cancelled():
                session.stop()
                raise RuntimeError(tr("Measurement stopped by user."))
            if time.time() - start_time > expected_duration + 5.0:
                session.stop()
                raise RuntimeError(tr("Audio playback timed out. Audio device may have stopped responding."))
            if session.error:
                session.stop()
                raise RuntimeError(str(session.error))
            if progress_callback:
                progress_pct = int(90.0 * (session.current_frame / session.total_frames))
                progress_callback(progress_pct)
            time.sleep(0.05)

        session.stop()
        if session.error:
            raise RuntimeError(str(session.error))
        return session.input_data

    def start_measurement(self):
        if self.worker and self.worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.worker = NonlinearSweepWorker(self)
        self.worker.start()

    def start_latency_calibration(self):
        if self.cal_worker and self.cal_worker.isRunning():
            return
        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.cal_worker = LatencyCalWorker(self)
        self.cal_worker.finished.connect(self._cleanup_dummy_callback)
        self.cal_worker.start()

    def stop_measurement(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self._cleanup_dummy_callback()

    def calibrate_latency(self):
        """Measures loopback latency using a short logarithmic chirp signal."""
        sample_rate = self.audio_engine.sample_rate
        duration = 0.5
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        chirp = 0.3 * signal_chirp(t, f0=20, t1=duration, f1=10000, method="logarithmic")

        # Zero-pad chirp to allow for buffer delays
        padding = int(0.5 * sample_rate)
        out_signal = np.concatenate([chirp, np.zeros(padding)])

        out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
        out_data[:, 0] = out_signal
        out_data[:, 1] = out_signal

        logger.info("Executing latency calibration chirp...")
        rec_data = self.run_play_rec(out_data, input_channels=2)

        # Use measurement channel (or channel 0) to align
        recorded = rec_data[:, self.meas_channel_index if rec_data.shape[1] > 1 else 0]

        # Calculate cross-correlation to find peak delay with sub-sample precision
        correlation = fftconvolve(recorded, np.flip(chirp), mode="full")
        lag = find_subsample_peak(correlation) - len(chirp) + 1

        self.latency_sec = max(0.0, lag / sample_rate)
        self.signals.latency_result.emit(self.latency_sec)
        logger.info(f"Calibration successful: Latency = {self.latency_sec * 1000:.2f} ms ({lag:.2f} samples)")

    def _generate_sss_and_inverse(self, sample_rate, amplitude=1.0):
        """
        Generates SSS signal and inverse match filter by delegating to the core implementation.
        Scaled by amplitude for playback.
        """
        sss, inv_filter = generate_sss_and_inverse(sample_rate, self.sweep_duration, self.start_freq, self.end_freq)
        return amplitude * sss, inv_filter

    def _execute_measurement(self, worker):
        sample_rate = self.audio_engine.sample_rate
        P = 5  # We support up to P=5 orders

        # 1. Define Amplitude Scanning Range
        max_amp = 10 ** (self.amplitude_db / 20)
        amplitudes = np.linspace(0.2, 1.0, self.num_amplitudes) * max_amp

        logger.info(f"Starting Batch SSS/PHM measurement. Scanned amplitudes (linear): {amplitudes}")

        responses_ref = []
        responses_meas = []

        total_sweeps = self.num_amplitudes * self.averages
        padding_samples = int(0.5 * sample_rate)  # 500ms tail padding

        # Generate the single reference sweep and matching analytical inverse filter
        sss, inv_filter = generate_sss_and_inverse(sample_rate, self.sweep_duration, self.start_freq, self.end_freq)
        single_sweep_len = len(sss)
        block_len = single_sweep_len + padding_samples

        # Add 1.0 second silence at the end for noise floor measurement if enabled
        noise_samples = int(1.0 * sample_rate) if getattr(self, "measure_noise_floor", True) else 0
        total_len = total_sweeps * block_len + noise_samples

        # 1. Construct unified continuous playback signal
        cont_signal = np.zeros(total_len, dtype=np.float32)
        for amp_idx, amp in enumerate(amplitudes):
            for avg in range(self.averages):
                sweep_idx = amp_idx * self.averages + avg
                start_pt = sweep_idx * block_len
                cont_signal[start_pt : start_pt + single_sweep_len] = amp * sss

        # Router output allocation
        out_data = np.zeros((total_len, 2), dtype=np.float32)
        if self.output_channel in {"L", "STEREO"}:
            out_data[:, 0] = cont_signal
        if self.output_channel in {"R", "STEREO"}:
            out_data[:, 1] = cont_signal

        if not worker.is_running:
            return

        # Progress reporting callback from play/record session
        def progress_cb(pct):
            if worker.is_running:
                self.signals.progress.emit(int(pct))

        # Execute PlayRec session (Single open/close session)
        try:
            rec_data = self.run_play_rec(
                out_data, input_channels=2, progress_callback=progress_cb, check_cancelled=lambda: not worker.is_running
            )
        except Exception as e:
            if not worker.is_running:
                logger.info("Measurement was stopped by user.")
                return
            logger.error("Batch play/record session failed: %s", e)
            raise e

        # Execute Offline Mode/Virtual Loopback emulation if active
        if getattr(self.audio_engine, "offline_mode", False):
            rec_data = np.zeros((total_len, 2), dtype=np.float32)
            simulated_meas = (
                cont_signal
                - 0.08 * (cont_signal**2)
                + 0.12 * (cont_signal**3)
                - 0.04 * (cont_signal**4)
                + 0.06 * (cont_signal**5)
            )
            rec_data[:, self.meas_channel_index] = simulated_meas
            rec_data[:, self.ref_channel_index] = cont_signal
            if getattr(self, "measure_noise_floor", True):
                noise_start = total_sweeps * block_len
                noise_sig = np.random.normal(0, 1e-5, noise_samples)  # -100 dBFS noise floor
                rec_data[noise_start:, self.meas_channel_index] = noise_sig

        # Quality Control: Peak Input Level check
        self.warnings = []
        ch_meas = self.meas_channel_index if rec_data.shape[1] > self.meas_channel_index else 0
        meas_peak = np.max(np.abs(rec_data[:, ch_meas]))
        meas_peak_db = float(20 * np.log10(meas_peak + 1e-12))

        if meas_peak >= 0.99:
            self.warnings.append(
                tr("Clipping detected on input signal (Peak: {0:.1f} dBFS). Lower sweep volume or input gain.").format(
                    meas_peak_db
                )
            )
        elif meas_peak < 1e-4:
            self.warnings.append(
                tr("No input signal detected (Peak: {0:.1f} dBFS). Check cables and routing.").format(meas_peak_db)
            )
        elif meas_peak < 0.0316:  # -30 dBFS
            self.warnings.append(
                tr(
                    "Low input level (Peak: {0:.1f} dBFS). Consider increasing volume or input gain for better accuracy."
                ).format(meas_peak_db)
            )

        # Choose alignment channel: Ref channel in XFER mode, Meas channel otherwise
        if self.input_mode in {"XFER", "XFER_REV"}:
            align_ch = self.ref_channel_index
        else:
            align_ch = self.meas_channel_index if rec_data.shape[1] > 1 else 0

        # Estimate and compensate clock drift between sweeps
        is_same_device = getattr(self.audio_engine, "input_device", None) == getattr(
            self.audio_engine, "output_device", None
        )
        if total_sweeps > 1 and not is_same_device:
            try:
                # 1. Estimate peak of the first sweep block
                first_block = rec_data[0:block_len, align_ch]
                first_ir = fftconvolve(first_block, inv_filter, mode="full")
                t_peak_first = find_subsample_peak(first_ir)

                # 2. Estimate peak of the last sweep block
                last_start = (total_sweeps - 1) * block_len
                last_end = last_start + block_len
                last_block = rec_data[last_start:last_end, align_ch]
                last_ir = fftconvolve(last_block, inv_filter, mode="full")
                t_peak_last = find_subsample_peak(last_ir)

                # 3. Compute drift factor (measured distance / expected distance)
                expected_distance = (total_sweeps - 1) * block_len
                measured_distance = expected_distance + (t_peak_last - t_peak_first)
                drift_factor = measured_distance / expected_distance
                drift_ppm = (drift_factor - 1.0) * 1e6

                logger.info("Estimated clock drift: %.2f ppm (factor: %.8f)", drift_ppm, drift_factor)

                # 4. Apply resampling if drift is significant (> 1.0 ppm) and physically plausible (< 1000.0 ppm)
                if 1.0 < np.abs(drift_ppm) < 1000.0:
                    logger.info("Applying clock drift compensation via high-quality windowed sinc resampling...")
                    rec_data_corrected = np.zeros_like(rec_data)
                    for ch in range(rec_data.shape[1]):
                        rec_data_corrected[:, ch] = sinc_resample(rec_data[:, ch], drift_factor)
                    rec_data = rec_data_corrected
                    logger.info("Clock drift compensation completed.")
                elif np.abs(drift_ppm) >= 1000.0:
                    logger.warning(
                        "Estimated clock drift (%.2f ppm) is physically implausible. "
                        "This likely indicates noise interference or peak-finding error. "
                        "Skipping compensation to prevent signal degradation.",
                        drift_ppm,
                    )
                    self.warnings.append(
                        tr(
                            "High clock drift or sync failure (Estimated: {0:.1f} ppm). Synchronization may be degraded."
                        ).format(drift_ppm)
                    )
            except Exception as e:
                logger.error("Failed to compensate clock drift: %s", e)

        # 2. Slice and Average in Memory
        for amp_idx, _amp in enumerate(amplitudes):
            if not worker.is_running:
                return

            accum_data = None
            ref_peak_sub = None

            for avg in range(self.averages):
                sweep_idx = amp_idx * self.averages + avg
                start_pt = sweep_idx * block_len
                end_pt = start_pt + block_len

                # Extract the sweep block
                rec_block = rec_data[start_pt:end_pt, :].copy()
                align_sig = rec_block[:, align_ch]

                # Deconvolve alignment channel to locate peak
                temp_ir = fftconvolve(align_sig, inv_filter, mode="full")
                t_peak = find_subsample_peak(temp_ir)

                if avg == 0:
                    accum_data = rec_block
                    ref_peak_sub = t_peak
                else:
                    delay = t_peak - ref_peak_sub

                    # Apply sub-sample fractional delay shift in frequency domain
                    shifted = np.zeros_like(rec_block)
                    for ch in range(rec_block.shape[1]):
                        shifted[:, ch] = apply_fractional_delay(rec_block[:, ch], -delay)

                    accum_data += shifted

            averaged_data = accum_data / self.averages

            # Deconvolution to get raw impulse responses
            sig_ref = averaged_data[:, self.ref_channel_index]
            sig_meas = averaged_data[:, self.meas_channel_index]

            ir_ref_raw = deconvolve_signal(sig_ref, sss)
            ir_meas_raw = deconvolve_signal(sig_meas, sss)

            responses_ref.append(ir_ref_raw)
            responses_meas.append(ir_meas_raw)

            # Update DSP progress (90% to 95%)
            progress_pct = 90 + int(5.0 * (amp_idx + 1) / self.num_amplitudes)
            self.signals.progress.emit(progress_pct)

        # 3. Noise Floor Measurement Extraction (Optional)
        noise_floor_dbfs = None
        if getattr(self, "measure_noise_floor", True) and noise_samples > 0:
            if worker.is_running:
                logger.info("Extracting noise floor from continuous recording...")
                noise_start = total_sweeps * block_len
                noise_sig = rec_data[noise_start:, self.meas_channel_index if rec_data.shape[1] > 1 else 0]

                try:
                    # Apply 20Hz-20kHz bandpass filtering
                    nyquist = sample_rate / 2.0
                    sos_hp = butter(4, 20.0 / nyquist, btype="highpass", output="sos")
                    filtered_sig = sosfilt(sos_hp, noise_sig)

                    if sample_rate > 44100:
                        sos_lp = butter(4, 20000.0 / nyquist, btype="lowpass", output="sos")
                        filtered_sig = sosfilt(sos_lp, filtered_sig)

                    # Trim edges to avoid transients
                    trim_start = int(sample_rate * 0.20)
                    trim_end = int(sample_rate * 0.10)
                    if len(filtered_sig) > (trim_start + trim_end):
                        trimmed_sig = filtered_sig[trim_start:-trim_end]
                    else:
                        trimmed_sig = filtered_sig

                    rms = np.sqrt(np.mean(trimmed_sig**2))
                    noise_floor_dbfs = float(20 * np.log10(rms + 1e-12))
                    logger.info("Extracted noise floor: %.2f dBFS", noise_floor_dbfs)
                except Exception as e:
                    logger.error("Failed to extract noise floor: %s", e)
        self.measured_noise_floor_dbfs = noise_floor_dbfs

        # Check SNR if noise floor is measured and we have responses
        if noise_floor_dbfs is not None and len(responses_meas) > 0:
            ir_peak = np.max(np.abs(responses_meas[-1]))
            ir_peak_db = float(20 * np.log10(ir_peak + 1e-12))
            snr = ir_peak_db - noise_floor_dbfs
            if snr < 20.0:
                self.warnings.append(
                    tr(
                        "Low SNR ({0:.1f} dB). Harmonic plots may be noisy and unreliable due to background noise."
                    ).format(snr)
                )

        # 3. Parallel Hammerstein Separation and Analysis using Core Module
        (
            valid_freqs,
            magnitudes_db_dict,
            phases_deg_dict,
            time_ms,
            separated_kernels_data,
        ) = process_amplitude_responses(
            responses_meas,
            responses_ref,
            sample_rate,
            self.start_freq,
            self.end_freq,
            self.input_mode,
            self.latency_sec,
            sweep_duration=self.sweep_duration,
            P=P,
            amplitudes=amplitudes,
            unwrap_phase=True,
        )

        self.signals.progress.emit(95)

        # Push to active model cache
        try:
            from src.core.hammerstein_model import set_active_model

            ref_max = np.max(np.abs(separated_kernels_data[0])) if len(separated_kernels_data) > 0 else 1.0

            if self.input_mode in {"XFER", "XFER_REV"} and len(responses_ref) > 0 and len(amplitudes) > 0:
                g_ref = float(np.max(np.abs(responses_ref[-1])) / amplitudes[-1])
            else:
                g_ref = 1.0

            cache_data = {
                "metadata": {
                    "module": self.name,
                    "sample_rate": sample_rate,
                    "num_amplitudes": self.num_amplitudes,
                    "sweep_duration": self.sweep_duration,
                    "start_freq": self.start_freq,
                    "end_freq": self.end_freq,
                    "input_mode": self.input_mode,
                    "latency_sec": self.latency_sec,
                    "ref_max": float(ref_max),
                    "g_ref": g_ref,
                    "P": len(separated_kernels_data),
                    "noise_floor_dbfs": noise_floor_dbfs,
                },
                "time_domain": {
                    "time_ms": time_ms,
                    "kernels": {f"h{p + 1}": separated_kernels_data[p] for p in range(len(separated_kernels_data))},
                },
                "frequency_domain": {
                    "freqs": valid_freqs,
                    "magnitudes_db": {k: v for k, v in magnitudes_db_dict.items() if k.startswith("h")},
                    "phases_deg": {k: v for k, v in phases_deg_dict.items() if k.startswith("h") or k == "ref_phase"},
                },
            }
            set_active_model(cache_data)
            logger.info("Successfully pushed measured Hammerstein model to active cache.")
        except Exception as cache_err:
            logger.error("Failed to push model to cache: %s", cache_err)

        # Emit plots
        self.signals.update_plot.emit(valid_freqs, magnitudes_db_dict, phases_deg_dict)
        self.signals.update_kernels.emit(time_ms, separated_kernels_data)
        self.signals.progress.emit(100)


class NonlinearAnalyzerWidget(QWidget):
    def __init__(self, module: NonlinearAnalyzer):
        QWidget.__init__(self)
        self.module = module

        self.init_ui()

        # Connect Signals
        self.module.signals.update_plot.connect(self.on_update_plot)
        self.module.signals.update_kernels.connect(self.on_update_kernels)
        self.module.signals.sweep_finished.connect(self.on_sweep_finished)
        self.module.signals.progress.connect(self.progress_bar.setValue)
        self.module.signals.latency_result.connect(self.on_latency_result)
        self.module.signals.error.connect(self.on_error)

        # Stored data cache for comparisons
        self.cached_freqs = None
        self.cached_mags = {}
        self.cached_phases = {}
        self.cached_kernels = None
        self.cached_time_ms = None

    def init_ui(self):
        # Premium layout design
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # --- Sidebar Container (Left Side, Fixed Width) ---
        sidebar_container = QWidget()
        sidebar_container.setFixedWidth(300)
        sidebar_main_layout = QVBoxLayout(sidebar_container)
        sidebar_main_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_main_layout.setSpacing(10)

        # --- Parameter Scroll Area ---
        parameter_scroll = QScrollArea()
        parameter_scroll.setWidgetResizable(True)
        parameter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        parameter_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        parameter_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(10)

        # Group 1: General Sweep Parameters
        sweep_group = QGroupBox(tr("Swept Sine Settings"))
        sweep_form = QFormLayout(sweep_group)
        sweep_form.setContentsMargins(6, 8, 6, 8)
        sweep_form.setSpacing(6)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(2, 20000)
        self.start_spin.setValue(self.module.start_freq)
        self.start_spin.valueChanged.connect(lambda v: setattr(self.module, "start_freq", v))
        sweep_form.addRow(tr("Start Freq (Hz):"), self.start_spin)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(20, 24000)
        self.end_spin.setValue(self.module.end_freq)
        self.end_spin.valueChanged.connect(lambda v: setattr(self.module, "end_freq", v))
        sweep_form.addRow(tr("End Freq (Hz):"), self.end_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.5, 30.0)
        self.duration_spin.setSingleStep(0.5)
        self.duration_spin.setValue(self.module.sweep_duration)
        self.duration_spin.valueChanged.connect(lambda v: setattr(self.module, "sweep_duration", v))
        sweep_form.addRow(tr("Sweep Time (s):"), self.duration_spin)

        self.tsa_spin = QSpinBox()
        self.tsa_spin.setRange(1, 20)
        self.tsa_spin.setValue(self.module.averages)
        self.tsa_spin.valueChanged.connect(lambda v: setattr(self.module, "averages", v))
        sweep_form.addRow(tr("Averages (Time-Sync):"), self.tsa_spin)

        scroll_layout.addWidget(sweep_group)

        # Group 2: Parallel Hammerstein Model Parameters
        phm_group = QGroupBox(tr("Nonlinear Modeling"))
        phm_form = QFormLayout(phm_group)
        phm_form.setContentsMargins(6, 8, 6, 8)
        phm_form.setSpacing(6)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-60.0, 0.0)
        self.amp_spin.setSingleStep(1.0)
        self.amp_spin.setValue(self.module.amplitude_db)
        self.amp_spin.valueChanged.connect(lambda v: setattr(self.module, "amplitude_db", v))
        phm_form.addRow(tr("Max Amp (dBFS):"), self.amp_spin)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(5, 10)  # Safe range to keep execution < 30s
        self.steps_spin.setValue(self.module.num_amplitudes)
        self.steps_spin.valueChanged.connect(lambda v: setattr(self.module, "num_amplitudes", v))
        phm_form.addRow(tr("Amplitude Steps (Max Order 5):"), self.steps_spin)

        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), "None")
        self.smooth_combo.addItem(tr("Low Smoothing"), "Light")
        self.smooth_combo.addItem(tr("Medium Smoothing"), "Medium")
        self.smooth_combo.addItem(tr("High Smoothing"), "Heavy")
        self.smooth_combo.setCurrentIndex(1)  # Default: Light
        self.smooth_combo.currentIndexChanged.connect(self.refresh_plots_with_smoothing)
        phm_form.addRow(tr("Graph Smoothing:"), self.smooth_combo)

        self.chk_unwrap = QCheckBox(tr("Unwrap Phase"))
        self.chk_unwrap.setChecked(False)
        self.chk_unwrap.toggled.connect(self.refresh_plots_with_smoothing)
        phm_form.addRow("", self.chk_unwrap)

        scroll_layout.addWidget(phm_group)

        # Group 3: Routing & Calibration
        route_group = QGroupBox(tr("Routing & Calibration"))
        route_form = QFormLayout(route_group)
        route_form.setContentsMargins(6, 8, 6, 8)
        route_form.setSpacing(6)

        self.out_combo = QComboBox()
        self.out_combo.addItem(tr("Left"), "L")
        self.out_combo.addItem(tr("Right"), "R")
        self.out_combo.addItem(tr("Stereo"), "STEREO")
        self.out_combo.setCurrentIndex(2)  # Default: Stereo
        self.out_combo.currentIndexChanged.connect(self.on_routing_changed)
        route_form.addRow(tr("Output Ch:"), self.out_combo)

        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("Single Ch (Left Ch1)"), "L")
        self.in_mode_combo.addItem(tr("Single Ch (Right Ch2)"), "R")
        self.in_mode_combo.addItem(tr("2-Ch Relative (Ref=L, Meas=R)"), "XFER")
        self.in_mode_combo.addItem(tr("2-Ch Relative (Ref=R, Meas=L)"), "XFER_REV")
        self.in_mode_combo.setCurrentIndex(3)  # Default: XFER (Ref=R, Meas=L)
        self.in_mode_combo.currentIndexChanged.connect(self.on_routing_changed)
        route_form.addRow(tr("Input Mode:"), self.in_mode_combo)

        # Latency Display
        self.latency_label = QLabel("0.00 ms")
        self.latency_label.setStyleSheet("font-weight: bold; color: #4ba3e3;")
        route_form.addRow(tr("Delay Time:"), self.latency_label)

        # Calibrate Button
        self.cal_btn = QPushButton(tr("Measure Delay"))
        self.cal_btn.clicked.connect(self.module.start_latency_calibration)
        route_form.addRow(self.cal_btn)

        scroll_layout.addWidget(route_group)

        scroll_layout.addStretch()
        scroll_content.setLayout(scroll_layout)
        parameter_scroll.setWidget(scroll_content)
        sidebar_main_layout.addWidget(parameter_scroll)

        # --- Fixed Measurement Controls (Bottom) ---
        ctrl_container = QWidget()
        ctrl_main_layout = QVBoxLayout(ctrl_container)
        ctrl_main_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_main_layout.setSpacing(8)

        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton(tr("Start Analysis"))
        self.start_btn.setStyleSheet(
            "background-color: #2b8c56; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        self.start_btn.clicked.connect(self.start_measurement)
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_measurement)
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_main_layout.addLayout(ctrl_layout)

        # Export Button
        self.export_btn = QPushButton(tr("Export Model..."))
        self.export_btn.setStyleSheet(
            "background-color: #4ba3e3; color: white; font-weight: bold; padding: 6px 12px; border-radius: 4px;"
        )
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_model)
        ctrl_main_layout.addWidget(self.export_btn)

        # Progress bar
        self.progress_bar = QProgressBar()

        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        ctrl_main_layout.addWidget(self.progress_bar)

        # Status/Warning label (subtle, displayed only when warnings exist)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #e68c14;")
        self.status_label.setWordWrap(True)
        ctrl_main_layout.addWidget(self.status_label)

        sidebar_main_layout.addWidget(ctrl_container)
        main_layout.addWidget(sidebar_container)

        # --- Plot Content Area (Right Side, Tab Widget) ---
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(450)

        # Tab 1: Magnitude Response (Bode Plot)
        self.mag_tab = QWidget()
        mag_layout = QVBoxLayout(self.mag_tab)
        self.mag_plot = pg.PlotWidget(title=tr("Bode Magnitude Response"))
        self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(True, False)
        self.mag_plot.showGrid(True, True, alpha=0.3)
        mag_layout.addWidget(self.mag_plot)
        self.plot_tabs.addTab(self.mag_tab, tr("Magnitude Response"))

        # Tab 2: Phase Response
        self.phase_tab = QWidget()
        phase_layout = QVBoxLayout(self.phase_tab)
        self.phase_plot = pg.PlotWidget(title=tr("Bode Phase Response"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(True, False)
        self.phase_plot.showGrid(True, True, alpha=0.3)
        phase_layout.addWidget(self.phase_plot)
        self.plot_tabs.addTab(self.phase_tab, tr("Phase Response"))

        # Tab 3: Time Domain Kernels h_p(t)
        self.kernel_tab = QWidget()
        kernel_layout = QVBoxLayout(self.kernel_tab)
        self.kernel_plot = pg.PlotWidget(title=tr("Nonlinear Impulse Responses (Kernels)"))
        self.kernel_plot.setLabel("left", tr("Normalized Amplitude"))
        self.kernel_plot.setLabel("bottom", tr("Time"), units="ms")
        self.kernel_plot.showGrid(True, True, alpha=0.3)
        kernel_layout.addWidget(self.kernel_plot)
        self.plot_tabs.addTab(self.kernel_tab, tr("Impulse Responses (Kernels)"))

        # Premium Plot Legends
        self.mag_plot.addLegend(offset=(10, 10))
        self.phase_plot.addLegend(offset=(10, 10))
        self.kernel_plot.addLegend(offset=(10, 10))

        main_layout.addWidget(self.plot_tabs, stretch=1)
        self.update_frequency_limits()
        self.on_routing_changed()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_frequency_limits()

    def update_frequency_limits(self):
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0

        self.start_spin.blockSignals(True)
        self.start_spin.setRange(2.0, nyquist)
        if self.start_spin.value() > nyquist:
            self.start_spin.setValue(min(20.0, nyquist))
            self.module.start_freq = self.start_spin.value()
        self.start_spin.blockSignals(False)

        self.end_spin.blockSignals(True)
        self.end_spin.setRange(20.0, nyquist)
        if self.end_spin.value() > nyquist:
            self.end_spin.setValue(nyquist)
            self.module.end_freq = nyquist
        self.end_spin.blockSignals(False)

    def update_latency_display(self):
        mode = self.module.input_mode
        if mode in {"XFER", "XFER_REV"}:
            self.cal_btn.setEnabled(False)
            self.latency_label.setEnabled(False)
            self.latency_label.setText(tr("Not Required (2-Ch Relative)"))
            self.latency_label.setStyleSheet("font-weight: bold; color: #888888;")
        else:
            self.cal_btn.setEnabled(True)
            self.latency_label.setEnabled(True)
            if self.module.latency_sec == 0.0:
                self.latency_label.setText(tr("0.00 ms (Uncalibrated)"))
                self.latency_label.setStyleSheet("font-weight: bold; color: #e68c14;")
            else:
                self.latency_label.setText(tr("{0:.2f} ms (Calibrated)").format(self.module.latency_sec * 1000))
                self.latency_label.setStyleSheet("font-weight: bold; color: #2b8c56;")

    def on_routing_changed(self):
        mode = self.in_mode_combo.currentData()
        self.module.input_mode = mode
        if mode == "L":
            self.module.meas_channel_index = 0
            self.module.ref_channel_index = 0
        elif mode == "R":
            self.module.meas_channel_index = 1
            self.module.ref_channel_index = 1
        elif mode == "XFER_REV":
            self.module.meas_channel_index = 0
            self.module.ref_channel_index = 1
        else:  # XFER
            self.module.meas_channel_index = 1
            self.module.ref_channel_index = 0

        self.module.output_channel = self.out_combo.currentData()
        self.update_latency_display()

    def start_measurement(self):
        # Turn off main audio engine stream if running to capture hardware exclusively
        if self.module.audio_engine.stream and self.module.audio_engine.stream.active:
            self.module.audio_engine.stop_stream()

        self.start_btn.setEnabled(False)
        self.cal_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("")

        # Clear existing plots
        self.mag_plot.clear()
        self.phase_plot.clear()
        self.kernel_plot.clear()

        self.module.start_measurement()

    def stop_measurement(self):
        self.module.stop_measurement()
        self.on_sweep_finished()

    def on_sweep_finished(self):
        self.start_btn.setEnabled(True)
        self.update_latency_display()
        self.stop_btn.setEnabled(False)

        # Notify MainWindow that the active model has changed, so other modules (e.g. ResponseViewer) can update their cache buttons
        from PyQt6.QtWidgets import QApplication
        from src.gui.main_window import MainWindow

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.notify_active_model_changed()
                break

        # Display quality warning issues if any
        if getattr(self.module, "warnings", []):
            warning_text = "\n".join([f"⚠️ {w}" for w in self.module.warnings])
            self.status_label.setText(warning_text)
        else:
            self.status_label.setText("")

    def on_latency_result(self, val):
        self.update_latency_display()
        QMessageBox.information(
            self, tr("Calibration Successful"), tr("Measured loopback delay: {0:.2f} ms").format(val * 1000)
        )

    def on_error(self, message):
        QMessageBox.critical(self, tr("Measurement Error"), message)
        self.on_sweep_finished()

    def refresh_plots_with_smoothing(self):
        if self.cached_freqs is not None:
            self.on_update_plot(self.cached_freqs, self.cached_mags, self.cached_phases)

    def apply_smoothing(self, y_data, level):
        if level == "None" or len(y_data) < 15:
            return y_data

        window_size = 15
        if level == "Medium":
            window_size = 35
        elif level == "Heavy":
            window_size = 75

        window_size = min(window_size, len(y_data) - 1)
        if window_size % 2 == 0:
            window_size -= 1

        if window_size < 5:
            return y_data

        try:
            return savgol_filter(y_data, window_size, polyorder=2)
        except Exception as e:
            logger.warning("Smoothing failed: %s", e)
            return y_data

    def on_update_plot(self, freqs, magnitudes_db_dict, phases_deg_dict):
        self.cached_freqs = freqs
        self.cached_mags = magnitudes_db_dict
        self.cached_phases = phases_deg_dict

        if self.cached_kernels is not None:
            self.export_btn.setEnabled(True)

        # Retrieve current display smoothing level
        smooth_level = self.smooth_combo.currentData()

        # Premium Palette
        # h1: Light blue, h2: Green, h3: Amber/Orange, h4: Magenta/Pink, h5: Crimson Red
        colors = {
            "h1": (75, 163, 227),  # #4ba3e3
            "h2": (43, 140, 86),  # #2b8c56
            "h3": (230, 140, 20),  # #e68c14
            "h4": (200, 50, 160),  # #c832a0
            "h5": (217, 83, 79),  # #d9534f
        }

        labels = {
            "h1": tr("Fundamental (1st Order)"),
            "h2": tr("2nd Order Harmonic"),
            "h3": tr("3rd Order Harmonic"),
            "h4": tr("4th Order Harmonic"),
            "h5": tr("5th Order Harmonic"),
        }

        # Clear existing curves before redrawing
        self.mag_plot.clear()
        self.phase_plot.clear()

        # Plot measured Noise Floor if available
        if self.module.measured_noise_floor_dbfs is not None:
            noise_floor_arr = np.full_like(freqs, self.module.measured_noise_floor_dbfs)
            pen_noise = pg.mkPen(color=(150, 150, 150), width=1.2, style=Qt.PenStyle.DashLine)
            self.mag_plot.plot(freqs, noise_floor_arr, pen=pen_noise, name=tr("Noise Floor"))

        for key in ["h1", "h2", "h3", "h4", "h5"]:
            if key in magnitudes_db_dict:
                # Apply Savitzky-Golay Smoothing
                mag_smoothed = self.apply_smoothing(magnitudes_db_dict[key], smooth_level)
                phase_smoothed = self.apply_smoothing(phases_deg_dict[key], smooth_level)
                if not self.chk_unwrap.isChecked():
                    phase_smoothed = (phase_smoothed + 180) % 360 - 180

                # Magnitude Plot
                pen_mag = pg.mkPen(color=colors[key], width=2)
                self.mag_plot.plot(freqs, mag_smoothed, pen=pen_mag, name=labels[key])

                # Phase Plot
                pen_phase = pg.mkPen(color=colors[key], width=1.5, style=Qt.PenStyle.SolidLine)
                self.phase_plot.plot(freqs, phase_smoothed, pen=pen_phase, name=labels[key])

    def on_update_kernels(self, time_ms, separated_kernels_data):
        self.cached_time_ms = time_ms
        self.cached_kernels = separated_kernels_data

        self.kernel_plot.clear()

        # Auto-fit the X Range to focus on the impulse peak details
        if len(time_ms) > 0:
            self.kernel_plot.setXRange(time_ms[0], time_ms[-1])

        # Local normalization for visual display based on the peak of fundamental kernel h1
        ref_max = np.max(np.abs(separated_kernels_data[0])) if len(separated_kernels_data) > 0 else 1.0
        if ref_max < 1e-12:
            ref_max = 1.0

        colors = [
            (75, 163, 227),  # h1
            (43, 140, 86),  # h2
            (230, 140, 20),  # h3
            (200, 50, 160),  # h4
            (217, 83, 79),  # h5
        ]

        labels = [
            tr("1st Order (h1)"),
            tr("2nd Order (h2)"),
            tr("3rd Order (h3)"),
            tr("4th Order (h4)"),
            tr("5th Order (h5)"),
        ]

        for p in range(len(separated_kernels_data)):
            pen = pg.mkPen(color=colors[p], width=1.8)
            norm_kernel = separated_kernels_data[p] / ref_max
            self.kernel_plot.plot(time_ms, norm_kernel, pen=pen, name=labels[p])

        if self.cached_freqs is not None:
            self.export_btn.setEnabled(True)

    def export_model(self):
        if self.cached_freqs is None or self.cached_kernels is None:
            QMessageBox.warning(self, tr("Export Failed"), tr("No measurement data available to export."))
            return

        from PyQt6.QtWidgets import QFileDialog
        from src.core.hammerstein_model import save_hammerstein_model

        filepath, _ = QFileDialog.getSaveFileName(self, tr("Export Hammerstein Model"), "", tr("JSON Files (*.json)"))

        if not filepath:
            return

        try:
            ref_max = np.max(np.abs(self.cached_kernels[0])) if len(self.cached_kernels) > 0 else 1.0

            data = {
                "metadata": {
                    "module": self.module.name,
                    "sample_rate": self.module.audio_engine.sample_rate,
                    "num_amplitudes": self.module.num_amplitudes,
                    "sweep_duration": self.module.sweep_duration,
                    "start_freq": self.module.start_freq,
                    "end_freq": self.module.end_freq,
                    "input_mode": self.module.input_mode,
                    "latency_sec": self.module.latency_sec,
                    "ref_max": float(ref_max),
                    "P": len(self.cached_kernels),
                    "noise_floor_dbfs": self.module.measured_noise_floor_dbfs,
                },
                "time_domain": {
                    "time_ms": self.cached_time_ms,
                    "kernels": {f"h{p + 1}": self.cached_kernels[p] for p in range(len(self.cached_kernels))},
                },
                "frequency_domain": {
                    "freqs": self.cached_freqs,
                    "magnitudes_db": {k: v for k, v in self.cached_mags.items() if k.startswith("h")},
                    "phases_deg": {
                        k: v for k, v in self.cached_phases.items() if k.startswith("h") or k == "ref_phase"
                    },
                },
            }

            save_hammerstein_model(filepath, data)
            QMessageBox.information(self, tr("Export Successful"), tr("Model exported successfully."))
        except Exception as e:
            logger.error("Failed to export Hammerstein model to %s", filepath, exc_info=True)
            QMessageBox.critical(self, tr("Export Failed"), tr("Failed to save Hammerstein model: {0}").format(e))
