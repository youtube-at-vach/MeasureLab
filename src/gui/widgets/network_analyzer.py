import logging
import threading

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from scipy.signal import (
    chirp as signal_chirp,
)
from scipy.signal import (
    coherence,
    correlate,
    correlation_lags,
    fftconvolve,
    hilbert,
    savgol_filter,
    windows,
)

from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.core.utils import amplitude_to_linear, linear_to_amplitude
from src.measurement_modules.base import MeasurementModule

logger = logging.getLogger(__name__)


class NetworkAnalyzerSignals(QObject):
    update_plot = pyqtSignal(float, float, float, float)  # freq, mag_db, phase_deg, coherence
    update_ir_plot = pyqtSignal(object, object)  # time_ms, normalized_ir
    sweep_finished = pyqtSignal()
    progress = pyqtSignal(int)
    latency_result = pyqtSignal(float)
    ir_snr_result = pyqtSignal(float)
    error = pyqtSignal(str)
    harmonics_result = pyqtSignal(dict)  # dict containing harmonics data arrays


class PlayRecSession:
    def __init__(self, audio_engine, output_data, input_channels=1):
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
        # Prevent indefinite hang if audio engine failed to start the stream
        if self.audio_engine.stream is None and not getattr(self.audio_engine, "offline_mode", False):
            self.error = "Audio stream failed to start. Check ASIO settings (Sample Rate / Block Size)."
            self.is_complete = True
            self.completion_event.set()

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        completed = self.completion_event.wait(timeout)
        if not completed:
            self.error = "Audio playback timed out. The audio driver or hardware may have disconnected or stopped responding."
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

                # Output (Robust shape matching)
                ch_out = min(outdata.shape[1], self.output_data.shape[1])
                outdata[:chunk, :ch_out] = self.output_data[self.current_frame : self.current_frame + chunk, :ch_out]
                if ch_out < outdata.shape[1]:
                    outdata[:chunk, ch_out:] = 0
                if chunk < frames:
                    outdata[chunk:, :] = 0

                # Input (Robust shape matching)
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


class CalibrationWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer

    def run(self):
        self.analyzer.calibrate_latency()


class FastSweepWorker(QThread):
    def __init__(self, analyzer):
        super().__init__()
        self.analyzer = analyzer
        self.is_running = True

    def run(self):
        try:
            self.analyzer._execute_fast_sweep(self)
        except Exception as e:
            self.analyzer.signals.error.emit(str(e))
        finally:
            self.analyzer.signals.sweep_finished.emit()

    def stop(self):
        self.is_running = False


class NetworkAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.signals = NetworkAnalyzerSignals()

        # Parameters
        self.start_freq = 20.0
        self.end_freq = self.audio_engine.sample_rate / 2.0
        self.amplitude = 0.5
        self.gen_unit = "Amplitude"  # 'Amplitude', 'dBFS', 'dBV', 'dBu', 'Vrms', 'Vpeak'
        self.latency_sec = 0.0

        # Routing
        self.output_channel = "STEREO"  # 'L', 'R', 'STEREO'
        self.input_mode = "L"  # 'L', 'R', 'XFER', 'XTALK_LR', 'XTALK_RL'
        self.ref_channel_index = 0
        self.meas_channel_index = 1

        # Fast Sweep Parameters
        self.sweep_mode = "Fast Chirp"
        self.chirp_duration = 10.0
        self.averages = 1

        self.worker = None
        self.calibration_worker = None

        self.reference_trace = None

        self._dummy_callback_id = None
        self.signals.sweep_finished.connect(self._cleanup_dummy_callback)

    def _dummy_callback(self, indata, outdata, frames, time, status):
        pass

    def _cleanup_dummy_callback(self):
        if self._dummy_callback_id is not None:
            self.audio_engine.unregister_callback(self._dummy_callback_id)
            self._dummy_callback_id = None

    @property
    def name(self) -> str:
        return "Network Analyzer"

    @property
    def description(self) -> str:
        return "Bode Plot (Gain & Phase) with XFER support"

    def get_widget(self):
        return NetworkAnalyzerWidget(self)

    def run_play_rec(self, output_data, input_channels=1):
        """
        Helper to run a play/record session.
        output_data: (N, 2) numpy array
        Returns: (N, input_channels) numpy array
        """
        session = PlayRecSession(self.audio_engine, output_data, input_channels)
        session.start()
        expected_duration = len(output_data) / self.audio_engine.sample_rate
        session.wait(timeout=expected_duration + 2.0)
        session.stop()
        return session.input_data

    def get_output_amplitude(self):
        """Returns the linear amplitude (0-1) for signal generation."""
        # self.amplitude is already stored as linear amplitude (0-1) by the widget
        return max(0.0, min(1.0, self.amplitude))

    def calibrate_latency(self):
        """Measures loopback latency using a chirp signal."""
        sample_rate = self.audio_engine.sample_rate
        duration = 0.5

        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        chirp = signal_chirp(t, f0=20, t1=duration, f1=10000, method="logarithmic")
        chirp *= self.get_output_amplitude()

        try:
            out_data = np.zeros((len(chirp), 2), dtype=np.float32)
            out_data[:, 0] = chirp
            out_data[:, 1] = chirp

            logger.info("Playing chirp for latency calibration...")

            # Always capture 1 channel for latency cal (assume Ch 0 loopback)
            rec_data = self.run_play_rec(out_data, input_channels=1)
            recorded = rec_data[:, 0]

            correlation = correlate(recorded, chirp, mode="full")
            lags = correlation_lags(len(recorded), len(chirp), mode="full")
            lag = lags[np.argmax(correlation)]

            latency_samples = lag
            self.latency_sec = latency_samples / sample_rate

            if self.latency_sec < 0:
                self.latency_sec = 0

            self.signals.latency_result.emit(self.latency_sec)
            logger.info(f"Measured Latency: {self.latency_sec * 1000:.2f} ms")

        except Exception as e:
            self.signals.error.emit(f"Calibration failed: {e}")

    def start_sweep(self):
        if self.worker and self.worker.isRunning():
            return

        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.worker = FastSweepWorker(self)
        self.worker.start()

    def start_calibration(self):
        if self.calibration_worker and self.calibration_worker.isRunning():
            return

        if self._dummy_callback_id is None:
            self._dummy_callback_id = self.audio_engine.register_callback(self._dummy_callback)

        self.calibration_worker = CalibrationWorker(self)
        self.calibration_worker.finished.connect(self._cleanup_dummy_callback)
        self.calibration_worker.start()

    def stop_sweep(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()

        self._cleanup_dummy_callback()

    def _prepare_output_buffer(self, signal):
        """Prepares stereo output buffer based on routing."""
        out_data = np.zeros((len(signal), 2), dtype=np.float32)
        if self.output_channel in {"L", "STEREO"}:
            out_data[:, 0] = signal
        if self.output_channel in {"R", "STEREO"}:
            out_data[:, 1] = signal
        return out_data

    def _execute_fast_sweep(self, worker):
        sample_rate = self.audio_engine.sample_rate

        # 1. Generate Log Chirp & Inverse Filter
        chirp, inv_filter = self._generate_chirp_and_filter(sample_rate)

        self.signals.progress.emit(10)
        if not worker.is_running:
            return

        # 2. Play and Record (with averaging)
        accumulated_data = None
        reference_peak_idx = None

        # Determine the channel to use for time alignment
        if self.input_mode in {"XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"}:
            align_ch = self.ref_channel_index
        elif self.input_mode == "R":
            align_ch = 1
        else:
            align_ch = 0

        for i in range(self.averages):
            if not worker.is_running:
                return

            rec_data = self._record_sweep(chirp, sample_rate)

            # Find delay to align
            sig = rec_data[:, align_ch]
            ir = fftconvolve(sig, inv_filter, mode="full")
            peak_idx = np.argmax(np.abs(ir))

            if accumulated_data is None:
                accumulated_data = rec_data
                reference_peak_idx = peak_idx
            else:
                shift = reference_peak_idx - peak_idx
                shifted_data = np.roll(rec_data, shift, axis=0)

                # Zero out the rolled-over parts
                if shift > 0:
                    shifted_data[:shift, :] = 0
                elif shift < 0:
                    shifted_data[shift:, :] = 0

                accumulated_data += shifted_data

            # Progress update (10 to 50)
            progress = 10 + int(40 * (i + 1) / self.averages)
            self.signals.progress.emit(progress)

        if accumulated_data is None:
            return

        averaged_data = accumulated_data / self.averages

        # 3. Process
        self._process_sweep_data(averaged_data, inv_filter, chirp, sample_rate, worker)

        self.signals.progress.emit(100)

    def _record_sweep(self, chirp, sample_rate):
        """Prepares output buffer and runs the play/record session."""
        padding_sec = 1.0
        padding_samples = int(padding_sec * sample_rate)
        out_signal = np.concatenate([chirp, np.zeros(padding_samples)])
        out_data = self._prepare_output_buffer(out_signal)

        # Always capture stereo to avoid channel mapping issues
        input_ch_count = 2
        return self.run_play_rec(out_data, input_channels=input_ch_count)

    def _generate_chirp_and_filter(self, sample_rate):
        """Generates the logarithmic chirp signal and its inverse filter."""
        num_samples = int(sample_rate * self.chirp_duration)
        t = np.linspace(0, self.chirp_duration, num_samples, endpoint=False)

        w1 = 2 * np.pi * self.start_freq
        # w2 is not used but implicitly defined by end_freq in L
        T = self.chirp_duration
        L = np.log(self.end_freq / self.start_freq)

        phase = (w1 * T / L) * (np.exp(t * L / T) - 1)
        chirp = self.get_output_amplitude() * np.sin(phase)

        window = windows.tukey(num_samples, alpha=0.05)
        chirp *= window

        inv_envelope = np.exp(t * L / T)
        inv_filter = inv_envelope * np.sin(phase)
        inv_filter *= window
        inv_filter = np.flip(inv_filter)

        test_conv = fftconvolve(chirp, inv_filter, mode="full")
        norm_factor = np.max(np.abs(test_conv))
        if norm_factor > 1e-9:
            inv_filter /= norm_factor

        return chirp, inv_filter

    def _calculate_harmonics_data(
        self, ir_data, peak_idx, sample_rate, valid_freqs, H_ref_or_drive=None, freqs_ref_or_drive=None
    ):
        """
        Calculates individual harmonic responses using the Farina method (ESS).
        """
        L = np.log(self.end_freq / self.start_freq)
        harmonics = {
            "freqs": valid_freqs,
        }

        for N in range(2, 6):
            delta_t_N = self.chirp_duration * np.log(N) / L
            peak_N = peak_idx - int(sample_rate * delta_t_N)

            # Prevent overlap
            delta_t_next = self.chirp_duration * np.log(N + 1) / L
            dist_next = sample_rate * (delta_t_next - delta_t_N)

            delta_t_prev = self.chirp_duration * np.log(N - 1) / L
            dist_prev = sample_rate * (delta_t_N - delta_t_prev)

            pre_samples = min(int(0.005 * sample_rate), int(0.4 * dist_next))
            post_samples = min(int(0.030 * sample_rate), int(0.4 * dist_prev))

            start_idx = peak_N - pre_samples
            end_idx = peak_N + post_samples

            if start_idx >= 0 and end_idx < len(ir_data) and (end_idx - start_idx) > 8:
                ir_slice = ir_data[start_idx:end_idx]
                win = windows.tukey(len(ir_slice), alpha=0.1)
                ir_slice_win = ir_slice * win

                H_N = fft_manager.rfft(ir_slice_win)
                freqs_N = fft_manager.rfftfreq(len(ir_slice_win), d=1 / sample_rate)

                # Normalize
                if H_ref_or_drive is not None and freqs_ref_or_drive is not None:
                    H_ref_interp = np.interp(freqs_N, freqs_ref_or_drive, np.abs(H_ref_or_drive), left=1.0, right=1.0)
                    H_N_norm = H_N / (H_ref_interp + 1e-12)
                    mag_N = np.abs(H_N_norm)
                else:
                    mag_N = np.abs(H_N)

                # Map to fundamental grid
                freqs_fundamental = freqs_N / N
                mag_N_interp = np.interp(valid_freqs, freqs_fundamental, mag_N, left=1e-12, right=1e-12)
                harmonics[f"h{N}"] = 20 * np.log10(mag_N_interp + 1e-12)
            else:
                # If out of bounds or invalid, default to quiet level
                harmonics[f"h{N}"] = np.full_like(valid_freqs, -120.0)

        return harmonics

    def _process_sweep_data(self, rec_data, inv_filter, chirp, sample_rate, worker):
        """Processes the recorded sweep data to calculate magnitude and phase response, IR SNR, and Coherence."""

        def get_ir(signal):
            return fftconvolve(signal, inv_filter, mode="full")

        def normalize_ir(ir_data):
            peak = np.max(np.abs(ir_data)) if len(ir_data) else 0.0
            if peak <= 1e-12:
                return ir_data
            return ir_data / peak

        def emit_linear_ir(ir_data, peak_index, pre_samples, post_samples):
            ir_start = max(0, peak_index - pre_samples)
            ir_end = min(len(ir_data), peak_index + post_samples)
            if ir_end <= ir_start:
                return
            ir_slice = normalize_ir(ir_data[ir_start:ir_end])
            time_ms = (np.arange(ir_start, ir_end) - peak_index) / sample_rate * 1000.0
            self.signals.update_ir_plot.emit(time_ms, ir_slice)

        def emit_circular_ir(ir_data, peak_index, pre_samples, post_samples):
            if not len(ir_data):
                return
            offsets = np.arange(-pre_samples, post_samples)
            indices = (peak_index + offsets) % len(ir_data)
            ir_slice = normalize_ir(ir_data[indices])
            time_ms = offsets / sample_rate * 1000.0
            self.signals.update_ir_plot.emit(time_ms, ir_slice)

        ir_snr_db = None
        harmonics = {}

        if self.input_mode in {"XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"}:
            # XFER Mode: Ref = Ch0, Meas = Ch1 (Default) or Custom for Crosstalk
            ref_sig = rec_data[:, self.ref_channel_index]
            meas_sig = rec_data[:, self.meas_channel_index]

            ir_ref = get_ir(ref_sig)
            ir_meas = get_ir(meas_sig)

            # Find peak in Ref to align
            peak_idx = np.argmax(np.abs(ir_ref))

            # IR SNR Calculation
            noise_start = max(0, peak_idx - int(0.5 * sample_rate))
            noise_end = max(0, peak_idx - int(0.05 * sample_rate))
            if noise_end > noise_start:
                noise_segment = ir_meas[noise_start:noise_end]
                noise_rms = np.sqrt(np.mean(noise_segment**2))
                peak_val = np.abs(ir_meas[np.argmax(np.abs(ir_meas))])
                ir_snr_db = 20 * np.log10(peak_val / (noise_rms + 1e-12))

            # Window both
            pre = int(0.01 * sample_rate)
            post = int(0.5 * sample_rate)
            start = max(0, peak_idx - pre)
            end = min(len(ir_ref), peak_idx + post)

            # Ensure same length
            len_win = end - start

            win_ref = ir_ref[start:end]
            win_meas = ir_meas[start:end]

            H_ref = fft_manager.rfft(win_ref)
            H_meas = fft_manager.rfft(win_meas)
            freqs = fft_manager.rfftfreq(len_win, d=1 / sample_rate)

            # Transfer Function
            with np.errstate(divide="ignore", invalid="ignore"):
                H_xfer = H_meas / H_ref
                H_xfer = np.nan_to_num(H_xfer)

            relative_ir = fft_manager.irfft(H_xfer, n=len_win)
            relative_peak_idx = np.argmax(np.abs(relative_ir))
            emit_circular_ir(relative_ir, relative_peak_idx, pre, post)

            mask = (freqs >= self.start_freq) & (freqs <= self.end_freq)
            valid_freqs = freqs[mask]
            valid_H = H_xfer[mask]

            mag_db = 20 * np.log10(np.abs(valid_H) + 1e-12)
            phase_rad = np.angle(valid_H)
            phase_rad = np.unwrap(phase_rad)
            phase_deg = np.degrees(phase_rad)
            phase_deg = (phase_deg + 180) % 360 - 180

            # Coherence
            f_coh, coh = coherence(meas_sig, ref_sig, fs=sample_rate, nperseg=8192)
            coh_interp = np.interp(valid_freqs, f_coh, coh)

            # Calculate harmonics in XFER mode
            harmonics = self._calculate_harmonics_data(
                ir_data=ir_meas,
                peak_idx=peak_idx,
                sample_rate=sample_rate,
                valid_freqs=valid_freqs,
                H_ref_or_drive=H_ref,
                freqs_ref_or_drive=freqs,
            )
            harmonics["fundamental"] = mag_db

        else:
            # Single Channel Mode
            ch_idx = 0
            if self.input_mode == "R":
                ch_idx = 1

            if rec_data.shape[1] == 1:
                sig = rec_data[:, 0]
            else:
                sig = rec_data[:, ch_idx]

            ir = get_ir(sig)
            peak_idx = np.argmax(np.abs(ir))

            noise_start = max(0, peak_idx - int(0.5 * sample_rate))
            noise_end = max(0, peak_idx - int(0.05 * sample_rate))
            if noise_end > noise_start:
                noise_segment = ir[noise_start:noise_end]
                noise_rms = np.sqrt(np.mean(noise_segment**2))
                peak_val = np.abs(ir[peak_idx])
                ir_snr_db = 20 * np.log10(peak_val / (noise_rms + 1e-12))

            pre = int(0.01 * sample_rate)
            post = int(0.5 * sample_rate)
            start = max(0, peak_idx - pre)
            end = min(len(ir), peak_idx + post)
            emit_linear_ir(ir, peak_idx, pre, post)

            ir_win = ir[start:end]
            # Normalize by the known excitation/deconvolution chain so that a unity
            # loopback is near 0 dB independent of output amplitude.
            ir_drive = get_ir(chirp)
            drive_peak_idx = np.argmax(np.abs(ir_drive))
            drive_start = max(0, drive_peak_idx - pre)
            drive_end = min(len(ir_drive), drive_peak_idx + post)
            drive_win = ir_drive[drive_start:drive_end]

            len_win = min(len(ir_win), len(drive_win))
            if len_win < 8:
                len_win = len(ir_win)
                ir_ref_win = ir_win
                drive_ref_win = None
            else:
                ir_ref_win = ir_win[:len_win]
                drive_ref_win = drive_win[:len_win]

            H = fft_manager.rfft(ir_ref_win)
            freqs = fft_manager.rfftfreq(len(ir_ref_win), d=1 / sample_rate)
            H_norm = None
            if drive_ref_win is not None:
                H_drive = fft_manager.rfft(drive_ref_win)
                with np.errstate(divide="ignore", invalid="ignore"):
                    H_norm = np.nan_to_num(H / (H_drive + 1e-12))

            mask = (freqs >= self.start_freq) & (freqs <= self.end_freq)
            valid_freqs = freqs[mask]
            valid_H = H_norm[mask] if H_norm is not None else H[mask]

            mag_db = 20 * np.log10(np.abs(valid_H) + 1e-12)
            phase_rad = np.angle(valid_H)
            phase_rad = np.unwrap(phase_rad)

            # Latency compensation is only required when we use the raw transfer
            # (non-normalized) path. In normalized mode, drive path delay/phase is
            # already canceled by H/H_drive.
            if H_norm is None:
                delay_samples = peak_idx - start
                phase_rad += 2 * np.pi * valid_freqs * (delay_samples / sample_rate)

            phase_deg = np.degrees(phase_rad)
            phase_deg = (phase_deg + 180) % 360 - 180

            # Coherence against ideal chirp
            min_len = min(len(sig), len(chirp))
            f_coh, coh = coherence(sig[:min_len], chirp[:min_len], fs=sample_rate, nperseg=8192)
            coh_interp = np.interp(valid_freqs, f_coh, coh)

            # Calculate harmonics in Single Channel mode
            harmonics = self._calculate_harmonics_data(
                ir_data=ir,
                peak_idx=peak_idx,
                sample_rate=sample_rate,
                valid_freqs=valid_freqs,
                H_ref_or_drive=H_drive if drive_ref_win is not None else None,
                freqs_ref_or_drive=freqs if drive_ref_win is not None else None,
            )
            harmonics["fundamental"] = mag_db

        if ir_snr_db is not None:
            self.signals.ir_snr_result.emit(ir_snr_db)

        if harmonics and len(valid_freqs) > 0:
            thd_linear = np.zeros_like(valid_freqs)
            for N in range(2, 6):
                h_key = f"h{N}"
                if h_key in harmonics:
                    thd_linear += (10 ** (harmonics[h_key] / 20)) ** 2
            thd_linear = np.sqrt(thd_linear)
            harmonics["thd"] = 20 * np.log10(thd_linear + 1e-12)
            self.signals.harmonics_result.emit(harmonics)

        # Emit
        step = max(1, len(valid_freqs) // 500)
        for i in range(0, len(valid_freqs), step):
            if not worker.is_running:
                break
            self.signals.update_plot.emit(valid_freqs[i], mag_db[i], phase_deg[i], coh_interp[i])


class NetworkAnalyzerWidget(QWidget):
    def __init__(self, module: NetworkAnalyzer):
        super().__init__()
        self.module = module
        self.init_ui()

        self.module.signals.update_plot.connect(self.update_plot)
        self.module.signals.update_ir_plot.connect(self.update_ir_plot)
        self.module.signals.sweep_finished.connect(self.on_sweep_finished)
        self.module.signals.progress.connect(self.progress_bar.setValue)
        self.module.signals.latency_result.connect(self.on_latency_result)
        self.module.signals.ir_snr_result.connect(self.on_ir_snr_result)
        self.module.signals.error.connect(self.on_error)
        self.module.signals.harmonics_result.connect(self.on_harmonics_result)

        self.freqs = []
        self.mags = []
        self.phases = []
        self.cohs = []
        self.ir_times_ms = []
        self.ir_values = []
        self.etc_times_ms = []
        self.etc_db = []
        self.harmonics_data = {}
        self._riaa_auto_offset = 0.0

        # Decouple plot updates
        self.update_timer = QTimer()
        self._needs_plot_update = False
        self.update_timer.timeout.connect(self.on_update_timer)

    def _create_settings_tab(self) -> QWidget:
        settings_tab = QWidget()
        settings_layout = QVBoxLayout()
        controls_group = QGroupBox(tr("Sweep Settings"))
        form = QFormLayout()

        self.out_combo = QComboBox()
        self.out_combo.addItem(tr("Left"), "L")
        self.out_combo.addItem(tr("Right"), "R")
        self.out_combo.addItem(tr("Stereo"), "STEREO")
        self.out_combo.setCurrentIndex(2)
        self.out_combo.currentIndexChanged.connect(self.on_routing_changed)
        form.addRow(tr("Output Ch:"), self.out_combo)

        self.in_combo = QComboBox()
        self.in_combo.addItem(tr("Left (Ch1)"), "L")
        self.in_combo.addItem(tr("Right (Ch2)"), "R")
        self.in_combo.addItem(tr("XFER (Ref=L, Meas=R)"), "XFER")
        self.in_combo.addItem(tr("XFER (Ref=R, Meas=L)"), "XFER_REV")
        self.in_combo.addItem(tr("Crosstalk L -> R"), "XTALK_LR")
        self.in_combo.addItem(tr("Crosstalk R -> L"), "XTALK_RL")
        self.in_combo.setCurrentIndex(0)
        self.in_combo.currentIndexChanged.connect(self.on_routing_changed)
        form.addRow(tr("Input Mode:"), self.in_combo)

        self.start_spin = QDoubleSpinBox(controls_group)
        self.start_spin.setRange(10, 20000)
        self.start_spin.setValue(20)
        self.start_spin.valueChanged.connect(lambda v: setattr(self.module, "start_freq", v))
        form.addRow(tr("Start Freq:"), self.start_spin)

        self.end_spin = QDoubleSpinBox(controls_group)
        self.end_spin.setRange(10, 24000)
        self.end_spin.setValue(24000)
        self.end_spin.valueChanged.connect(lambda v: setattr(self.module, "end_freq", v))
        form.addRow(tr("End Freq:"), self.end_spin)

        self.duration_spin = QDoubleSpinBox(controls_group)
        self.duration_spin.setRange(0.1, 60.0)
        self.duration_spin.setValue(10.0)
        self.duration_spin.valueChanged.connect(lambda v: setattr(self.module, "chirp_duration", v))
        self.duration_label = QLabel(tr("Duration (s):"), controls_group)
        form.addRow(self.duration_label, self.duration_spin)

        self.avg_spin = QSpinBox(controls_group)
        self.avg_spin.setRange(1, 100)
        self.avg_spin.setValue(1)
        self.avg_spin.valueChanged.connect(lambda v: setattr(self.module, "averages", v))
        form.addRow(tr("Averages:"), self.avg_spin)

        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0, 1)
        self.amp_spin.setValue(0.5)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.valueChanged.connect(self.on_amp_spin_changed)

        self.gen_unit_combo = QComboBox()
        self.gen_unit_combo.addItems(["Amplitude", "dBFS", "dBV", "dBu", "Vrms", "Vpeak"])
        self.gen_unit_combo.currentTextChanged.connect(self.on_gen_unit_changed)

        amp_layout = QHBoxLayout()
        amp_layout.addWidget(self.amp_spin)
        amp_layout.addWidget(self.gen_unit_combo)
        form.addRow(tr("Amplitude:"), amp_layout)

        controls_group.setLayout(form)
        settings_layout.addWidget(controls_group)
        settings_layout.addStretch()
        settings_tab.setLayout(settings_layout)
        return settings_tab

    def _create_display_tab(self) -> QWidget:
        display_tab = QWidget()
        display_layout = QVBoxLayout()

        display_group = QGroupBox(tr("Display Settings"))
        display_form = QFormLayout()

        self.limit_check = QCheckBox(tr("Limit"))
        self.limit_check.setChecked(True)
        self.limit_check.toggled.connect(self.refresh_plots)
        self.limit_spin = QDoubleSpinBox()
        self.limit_spin.setRange(10, 24000)
        self.limit_spin.setValue(20000)
        self.limit_spin.valueChanged.connect(self.refresh_plots)

        limit_layout = QHBoxLayout()
        limit_layout.addWidget(self.limit_check)
        limit_layout.addWidget(self.limit_spin)
        display_form.addRow(tr("Max Freq:"), limit_layout)

        self.min_limit_check = QCheckBox(tr("Limit"))
        self.min_limit_check.setChecked(True)
        self.min_limit_check.toggled.connect(self.refresh_plots)
        self.min_limit_spin = QDoubleSpinBox()
        self.min_limit_spin.setRange(10, 24000)
        self.min_limit_spin.setValue(20)
        self.min_limit_spin.valueChanged.connect(self.refresh_plots)

        min_limit_layout = QHBoxLayout()
        min_limit_layout.addWidget(self.min_limit_check)
        min_limit_layout.addWidget(self.min_limit_spin)
        display_form.addRow(tr("Min Freq:"), min_limit_layout)

        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), None)
        self.smooth_combo.addItem(tr("1/1 Octave"), 1)
        self.smooth_combo.addItem(tr("1/3 Octave"), 3)
        self.smooth_combo.addItem(tr("1/6 Octave"), 6)
        self.smooth_combo.addItem(tr("1/12 Octave"), 12)
        self.smooth_combo.addItem(tr("1/24 Octave"), 24)
        self.smooth_combo.currentIndexChanged.connect(self.refresh_plots)
        display_form.addRow(tr("Smoothing:"), self.smooth_combo)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dBFS", "dBV", "dBu", "Vrms", "Vpeak"])
        self.unit_combo.currentTextChanged.connect(self.refresh_plots)
        display_form.addRow(tr("Unit:"), self.unit_combo)

        self.single_mode_combo = QComboBox()
        self.single_mode_combo.addItem(tr("Relative (Gain)"), "relative")
        self.single_mode_combo.addItem(tr("Absolute (Level)"), "absolute")
        self.single_mode_combo.currentIndexChanged.connect(self.on_display_mode_changed)
        display_form.addRow(tr("Single-Ch Mode:"), self.single_mode_combo)

        self.gd_check = QCheckBox(tr("Show Group Delay"))
        self.gd_check.toggled.connect(self.refresh_plots)
        display_form.addRow(self.gd_check)

        self.coh_check = QCheckBox(tr("Show Coherence"))
        self.coh_check.toggled.connect(self.refresh_plots)
        display_form.addRow(self.coh_check)

        display_group.setLayout(display_form)
        display_layout.addWidget(display_group)

        riaa_group = QGroupBox(tr("Reference Curves"))
        riaa_form = QFormLayout()

        self.riaa_check = QCheckBox(tr("Show RIAA Curve"))
        self.riaa_check.toggled.connect(self.refresh_plots)
        riaa_form.addRow(self.riaa_check)

        self.riaa_iec_check = QCheckBox(tr("Use IEC Amendment (7950µs)"))
        self.riaa_iec_check.toggled.connect(self.refresh_plots)
        riaa_form.addRow(self.riaa_iec_check)

        self.riaa_mode_combo = QComboBox()
        self.riaa_mode_combo.addItem(tr("Auto (200Hz - 5kHz Fit)"), "auto")
        self.riaa_mode_combo.addItem(tr("Manual"), "manual")
        self.riaa_mode_combo.currentIndexChanged.connect(self.on_riaa_mode_changed)
        riaa_form.addRow(tr("Alignment Mode:"), self.riaa_mode_combo)

        self.riaa_gain_spin = QDoubleSpinBox()
        self.riaa_gain_spin.setRange(-120, 120)
        self.riaa_gain_spin.setValue(0.0)
        self.riaa_gain_spin.setSuffix(" dB")
        self.riaa_gain_spin.valueChanged.connect(self.refresh_plots)
        self.riaa_gain_spin.setReadOnly(True)  # defaults to auto
        riaa_form.addRow(tr("Gain Offset (dB):"), self.riaa_gain_spin)

        riaa_group.setLayout(riaa_form)
        display_layout.addWidget(riaa_group)

        display_layout.addStretch()
        display_tab.setLayout(display_layout)
        return display_tab

    def _create_harmonics_settings_tab(self) -> QWidget:
        harmonics_settings_tab = QWidget()
        harmonics_settings_layout = QVBoxLayout()

        harmonics_group = QGroupBox(tr("Harmonics Display"))
        harmonics_form = QFormLayout()

        self.show_fundamental_check = QCheckBox(tr("Show Fundamental"))
        self.show_fundamental_check.setChecked(True)
        self.show_fundamental_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_fundamental_check)

        self.show_h2_check = QCheckBox(tr("Show 2nd Harmonic (H2)"))
        self.show_h2_check.setChecked(True)
        self.show_h2_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_h2_check)

        self.show_h3_check = QCheckBox(tr("Show 3rd Harmonic (H3)"))
        self.show_h3_check.setChecked(True)
        self.show_h3_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_h3_check)

        self.show_h4_check = QCheckBox(tr("Show 4th Harmonic (H4)"))
        self.show_h4_check.setChecked(True)
        self.show_h4_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_h4_check)

        self.show_h5_check = QCheckBox(tr("Show 5th Harmonic (H5)"))
        self.show_h5_check.setChecked(True)
        self.show_h5_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_h5_check)

        self.show_thd_check = QCheckBox(tr("Show THD"))
        self.show_thd_check.setChecked(True)
        self.show_thd_check.toggled.connect(self.refresh_harmonics_plot)
        harmonics_form.addRow(self.show_thd_check)

        self.harmonics_as_percent_check = QCheckBox(tr("Show as Percent (%)"))
        self.harmonics_as_percent_check.setChecked(False)
        self.harmonics_as_percent_check.toggled.connect(self.on_harmonics_as_percent_toggled)
        harmonics_form.addRow(self.harmonics_as_percent_check)

        harmonics_group.setLayout(harmonics_form)
        harmonics_settings_layout.addWidget(harmonics_group)
        harmonics_settings_layout.addStretch()
        harmonics_settings_tab.setLayout(harmonics_settings_layout)
        return harmonics_settings_tab

    def _create_calibration_tab(self) -> QWidget:
        cal_tab = QWidget()
        cal_tab_layout = QVBoxLayout()

        lat_group = QGroupBox(tr("Latency"))
        lat_form = QFormLayout()
        self.lat_btn = QPushButton(tr("Calibrate Latency"))
        self.lat_btn.clicked.connect(self.calibrate)
        lat_form.addRow(self.lat_btn)
        self.lat_label = QLabel(tr("Latency: 0.00 ms"))
        lat_form.addRow(self.lat_label)

        self.ir_snr_label = QLabel(tr("IR SNR: -- dB"))
        lat_form.addRow(self.ir_snr_label)

        lat_group.setLayout(lat_form)
        cal_tab_layout.addWidget(lat_group)

        cal_group = QGroupBox(tr("Reference Trace"))
        cal_layout = QFormLayout()
        self.store_ref_btn = QPushButton(tr("Store Reference"))
        self.store_ref_btn.clicked.connect(self.on_store_reference)
        cal_layout.addRow(self.store_ref_btn)
        self.clear_ref_btn = QPushButton(tr("Clear Reference"))
        self.clear_ref_btn.clicked.connect(self.on_clear_reference)
        cal_layout.addRow(self.clear_ref_btn)
        self.apply_ref_check = QCheckBox(tr("Apply Reference"))
        self.apply_ref_check.toggled.connect(self.on_apply_reference_changed)
        cal_layout.addRow(self.apply_ref_check)
        cal_group.setLayout(cal_layout)
        cal_tab_layout.addWidget(cal_group)

        cal_tab_layout.addStretch()
        cal_tab.setLayout(cal_tab_layout)
        return cal_tab

    def _create_bode_tab(self) -> QWidget:
        bode_tab = QWidget()
        plot_layout = QVBoxLayout(bode_tab)
        self.mag_plot = pg.PlotWidget(title=tr("Magnitude Response"))
        self.mag_plot.setLabel("left", tr("Magnitude"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(x=True, y=False)
        self.mag_plot.showGrid(x=True, y=True)
        self.mag_curve = self.mag_plot.plot(pen="g")

        self.riaa_curve = self.mag_plot.plot(pen=pg.mkPen("m", style=pg.QtCore.Qt.PenStyle.DashLine))

        self.coh_axis = pg.AxisItem("right")
        self.coh_axis.setLabel(tr("Coherence"), units="")
        self.mag_plot.plotItem.layout.addItem(self.coh_axis, 2, 3)

        self.coh_view = pg.ViewBox()
        self.coh_axis.linkToView(self.coh_view)
        self.mag_plot.plotItem.scene().addItem(self.coh_view)
        self.coh_view.setXLink(self.mag_plot.plotItem.vb)
        self.coh_view.setYRange(0, 1.05, padding=0)

        self.coh_view.setLogMode(False, False)
        self.coh_curve = pg.PlotCurveItem(pen="c")
        self.coh_view.addItem(self.coh_curve)

        self.mag_plot.plotItem.vb.sigResized.connect(self.update_coh_views)

        plot_layout.addWidget(self.mag_plot)

        self.phase_plot = pg.PlotWidget(title=tr("Phase Response"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(x=True, y=False)
        self.phase_plot.showGrid(x=True, y=True)
        self.phase_plot.setXLink(self.mag_plot)
        self.phase_curve = self.phase_plot.plot(pen="y")

        self.gd_axis = pg.AxisItem("right")
        self.gd_axis.setLabel(tr("Group Delay"), units="s")
        self.phase_plot.plotItem.layout.addItem(self.gd_axis, 2, 3)

        self.gd_view = pg.ViewBox()
        self.gd_axis.linkToView(self.gd_view)
        self.phase_plot.plotItem.scene().addItem(self.gd_view)
        self.gd_view.setXLink(self.phase_plot.plotItem.vb)

        self.gd_view.setLogMode(False, False)

        self.gd_curve = pg.PlotCurveItem(pen="r")
        self.gd_view.addItem(self.gd_curve)

        self.phase_plot.plotItem.vb.sigResized.connect(self.update_gd_views)

        plot_layout.addWidget(self.phase_plot)
        return bode_tab

    def _create_ir_tab(self) -> QWidget:
        ir_tab = QWidget()
        ir_layout = QVBoxLayout(ir_tab)
        self.ir_plot = pg.PlotWidget(title=tr("Impulse Response Plot"))
        self.ir_plot.setLabel("left", tr("Normalized Amplitude"))
        self.ir_plot.setLabel("bottom", tr("Time"), units="ms")
        self.ir_plot.showGrid(x=True, y=True)
        self.ir_curve = self.ir_plot.plot(pen="c")
        ir_layout.addWidget(self.ir_plot)
        return ir_tab

    def _create_etc_tab(self) -> QWidget:
        etc_tab = QWidget()
        etc_layout = QVBoxLayout(etc_tab)
        etc_controls = QHBoxLayout()
        etc_controls.addWidget(QLabel(f"{tr('ETC')} {tr('Smoothing:')}"))
        self.etc_smooth_combo = QComboBox()
        self.etc_smooth_combo.addItem(tr("Off"), "off")
        self.etc_smooth_combo.addItem(tr("Light"), "light")
        self.etc_smooth_combo.addItem(tr("Medium"), "medium")
        self.etc_smooth_combo.addItem(tr("Heavy"), "heavy")
        self.etc_smooth_combo.currentIndexChanged.connect(self.refresh_etc_plot)
        etc_controls.addWidget(self.etc_smooth_combo)
        etc_controls.addStretch()
        etc_layout.addLayout(etc_controls)
        self.etc_plot = pg.PlotWidget(title=tr("Energy Time Curve Plot"))
        self.etc_plot.setLabel("left", tr("Level"), units="dB")
        self.etc_plot.setLabel("bottom", tr("Time"), units="ms")
        self.etc_plot.showGrid(x=True, y=True)
        self.etc_curve = self.etc_plot.plot(pen="m")
        etc_layout.addWidget(self.etc_plot)
        return etc_tab

    def _create_harmonics_tab(self) -> QWidget:
        harmonics_tab = QWidget()
        harmonics_layout = QVBoxLayout(harmonics_tab)
        self.harmonics_plot = pg.PlotWidget(title=tr("Harmonic Distortion"))
        self.harmonics_plot.setLabel("left", tr("Level"), units="dB")
        self.harmonics_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.harmonics_plot.setLogMode(x=True, y=False)
        self.harmonics_plot.showGrid(x=True, y=True)
        self.harmonics_plot.addLegend()

        self.h_curves = {
            "fundamental": self.harmonics_plot.plot(pen=pg.mkPen("g", width=2), name=tr("Fundamental")),
            "h2": self.harmonics_plot.plot(pen=pg.mkPen("r", width=1.5), name=tr("2nd Harmonic")),
            "h3": self.harmonics_plot.plot(pen=pg.mkPen("orange", width=1.5), name=tr("3rd Harmonic")),
            "h4": self.harmonics_plot.plot(pen=pg.mkPen("y", width=1.5), name=tr("4th Harmonic")),
            "h5": self.harmonics_plot.plot(pen=pg.mkPen("m", width=1.5), name=tr("5th Harmonic")),
            "thd": self.harmonics_plot.plot(
                pen=pg.mkPen("c", width=2, style=pg.QtCore.Qt.PenStyle.DashLine), name=tr("THD")
            ),
        }
        harmonics_layout.addWidget(self.harmonics_plot)
        return harmonics_tab

    def init_ui(self):
        layout = QHBoxLayout()

        left_panel = QWidget()
        left_panel.setFixedWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        tabs = QTabWidget()
        tabs.addTab(self._create_settings_tab(), tr("Settings"))
        tabs.addTab(self._create_display_tab(), tr("Display"))
        tabs.addTab(self._create_harmonics_settings_tab(), tr("Harmonics"))
        tabs.addTab(self._create_calibration_tab(), tr("Calibration"))

        left_layout.addWidget(tabs)

        self.start_btn = QPushButton(tr("Start Sweep"))
        self.start_btn.setCheckable(True)
        self.start_btn.clicked.connect(self.on_start_stop)
        self.start_btn.setFixedHeight(40)
        left_layout.addWidget(self.start_btn)

        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)

        layout.addWidget(left_panel)

        plot_tabs = QTabWidget()
        plot_tabs.addTab(self._create_bode_tab(), tr("Bode"))
        plot_tabs.addTab(self._create_ir_tab(), tr("Impulse Response"))
        plot_tabs.addTab(self._create_etc_tab(), tr("ETC"))
        plot_tabs.addTab(self._create_harmonics_tab(), tr("Harmonics"))

        layout.addWidget(plot_tabs)
        self.setLayout(layout)
        self.update_frequency_limits()
        self.on_routing_changed(self.in_combo.currentIndex())
    def on_riaa_mode_changed(self, index):
        mode = self.riaa_mode_combo.currentData()
        self.riaa_gain_spin.setReadOnly(mode == "auto")
        if mode == "auto":
            # Recompute auto offset using latest plotted data without sweeping penalty
            self.refresh_plots()
        else:
            self.refresh_plots()

    def _calculate_riaa_curve(self, freqs, use_iec=False):
        # RIAA Playback Curve (normalized to 1 kHz)
        t1 = 3180e-6
        t2 = 318e-6
        t3 = 75e-6
        t4 = 7950e-6  # IEC amendment

        def mag_squared(f):
            w = 2 * np.pi * f
            n = 1.0 + (w * t2) ** 2
            d = (1.0 + (w * t1) ** 2) * (1.0 + (w * t3) ** 2)
            res = n / d
            if use_iec:
                res *= (w * t4) ** 2 / (1.0 + (w * t4) ** 2)
            return res

        ms_1khz = mag_squared(1000.0)
        ms_f = mag_squared(freqs)
        return 10 * np.log10(ms_f / ms_1khz + 1e-12)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_frequency_limits()

    def update_frequency_limits(self):
        sample_rate = self.module.audio_engine.sample_rate
        nyquist = sample_rate / 2.0

        # We block signals to prevent redundant logic execution during limits update
        self.start_spin.blockSignals(True)
        self.start_spin.setRange(10, nyquist)
        if self.start_spin.value() > nyquist:
            self.start_spin.setValue(min(20.0, nyquist))
            self.module.start_freq = self.start_spin.value()
        self.start_spin.blockSignals(False)

        self.end_spin.blockSignals(True)
        self.end_spin.setRange(10, nyquist)
        if self.end_spin.value() > nyquist:
            self.end_spin.setValue(nyquist)
            self.module.end_freq = nyquist
        self.end_spin.blockSignals(False)

        self.limit_spin.blockSignals(True)
        self.limit_spin.setRange(10, nyquist)
        if self.limit_spin.value() > nyquist:
            self.limit_spin.setValue(nyquist)
        self.limit_spin.blockSignals(False)

        self.min_limit_spin.blockSignals(True)
        self.min_limit_spin.setRange(10, nyquist)
        if self.min_limit_spin.value() > nyquist:
            self.min_limit_spin.setValue(nyquist)
        self.min_limit_spin.blockSignals(False)

    def on_routing_changed(self, index):
        self.module.input_mode = self.in_combo.currentData()

        # Handle Crosstalk Macros
        if self.module.input_mode == "XTALK_LR":
            # Drive L, Meas R (Ref=L)
            self.module.output_channel = "L"
            self.module.ref_channel_index = 0
            self.module.meas_channel_index = 1

            # Lock Output Combo
            idx = self.out_combo.findData("L")
            if idx != -1:
                self.out_combo.setCurrentIndex(idx)
            self.out_combo.setEnabled(False)

        elif self.module.input_mode == "XTALK_RL":
            # Drive R, Meas L (Ref=R)
            self.module.output_channel = "R"
            self.module.ref_channel_index = 1
            self.module.meas_channel_index = 0

            # Lock Output Combo
            idx = self.out_combo.findData("R")
            if idx != -1:
                self.out_combo.setCurrentIndex(idx)
            self.out_combo.setEnabled(False)

        elif self.module.input_mode == "XFER":
            # Standard XFER
            self.module.ref_channel_index = 0
            self.module.meas_channel_index = 1
            self.out_combo.setEnabled(True)
            self.module.output_channel = self.out_combo.currentData()

        elif self.module.input_mode == "XFER_REV":
            # Reverse XFER (Ref=R, Meas=L)
            self.module.ref_channel_index = 1
            self.module.meas_channel_index = 0
            # Output selection remains flexible
            self.out_combo.setEnabled(True)
            self.module.output_channel = self.out_combo.currentData()

        else:
            # Single Channel
            self.out_combo.setEnabled(True)
            self.module.output_channel = self.out_combo.currentData()

        # Update UI hints
        is_transfer_mode = self.module.input_mode in {"XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"}

        if is_transfer_mode:
            if "XTALK" in self.module.input_mode:
                self.mag_plot.setTitle(tr("Crosstalk (Meas / Ref)"))
            else:
                self.mag_plot.setTitle(tr("Transfer Function (Meas / Ref)"))
            self.single_mode_combo.setEnabled(False)
            self.unit_combo.setEnabled(False)  # Transfer mode is always relative dB
            self.coh_check.setEnabled(True)
        else:
            self.mag_plot.setTitle(tr("Magnitude Response"))
            self.single_mode_combo.setEnabled(True)
            self.unit_combo.setEnabled(self.single_mode_combo.currentData() == "absolute")
            self.coh_check.setChecked(False)
            self.coh_check.setEnabled(False)

    def on_display_mode_changed(self, index):
        is_transfer_mode = self.module.input_mode in {"XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"}
        if not is_transfer_mode:
            self.unit_combo.setEnabled(self.single_mode_combo.currentData() == "absolute")
        self.refresh_plots()

    def on_gen_unit_changed(self, unit):
        self.module.gen_unit = unit
        # Update display to show current amplitude in new unit
        self.update_amp_display_value(self.module.amplitude)

    def update_amp_display_value(self, amp_0_1):
        unit = self.gen_unit_combo.currentText()
        try:
            gain = self.module.audio_engine.calibration.output_gain
        except Exception:
            gain = 1.0

        self.amp_spin.blockSignals(True)

        if unit == "Amplitude":
            self.amp_spin.setRange(0, 1.0)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setSuffix("")
        elif unit == "dBFS":
            self.amp_spin.setRange(-120, 0)
            self.amp_spin.setSingleStep(1.0)
            self.amp_spin.setSuffix(" dB")
        elif unit == "dBV":
            self.amp_spin.setRange(-120, 20)
            self.amp_spin.setSingleStep(1.0)
            self.amp_spin.setSuffix(" dB")
        elif unit == "dBu":
            self.amp_spin.setRange(-120, 20)
            self.amp_spin.setSingleStep(1.0)
            self.amp_spin.setSuffix(" dB")
        elif unit == "Vrms":
            self.amp_spin.setRange(0, 100)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setSuffix(" V")
        elif unit == "Vpeak":
            self.amp_spin.setRange(0, 100)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setSuffix(" V")

        val = linear_to_amplitude(amp_0_1, unit, gain)
        self.amp_spin.setValue(val)

        self.amp_spin.blockSignals(False)

    def on_amp_spin_changed(self, val):
        unit = self.gen_unit_combo.currentText()
        try:
            gain = self.module.audio_engine.calibration.output_gain
        except Exception:
            gain = 1.0

        amp_0_1 = amplitude_to_linear(val, unit, gain)

        self.module.amplitude = amp_0_1

    def calibrate(self):
        self.lat_btn.setEnabled(False)
        self.lat_label.setText(tr("Calibrating..."))
        self.module.start_calibration()

    def on_latency_result(self, lat):
        self.lat_label.setText(tr("Latency: {0:.2f} ms").format(lat * 1000))
        self.lat_btn.setEnabled(True)

    def on_error(self, msg):
        logger.error(f"Error: {msg}")
        self.start_btn.setChecked(False)
        self.start_btn.setText(tr("Start Sweep"))

    def on_store_reference(self):
        if not self.freqs:
            return
        self.module.reference_trace = {
            "freqs": np.array(self.freqs),
            "mags": np.array(self.mags),
            "phases": np.array(self.phases),
            "gen_amp": float(self.module.amplitude),
        }
        logger.info("Reference trace stored.")

    def on_clear_reference(self):
        self.module.reference_trace = None
        self.refresh_plots()

    def on_apply_reference_changed(self, checked):
        self.refresh_plots()

    def on_start_stop(self, checked):
        if checked:
            self.update_frequency_limits()
            self.freqs = []
            self.mags = []
            self.phases = []
            self.cohs = []
            self.ir_times_ms = []
            self.ir_values = []
            self.etc_times_ms = []
            self.etc_db = []
            self.harmonics_data = {}
            self._needs_plot_update = False
            self.mag_curve.clear()
            self.phase_curve.clear()
            self.gd_curve.clear()
            self.coh_curve.clear()
            self.ir_curve.clear()
            self.etc_curve.clear()
            for curve in self.h_curves.values():
                curve.clear()
            self.ir_snr_label.setText(tr("IR SNR: -- dB"))
            self.start_btn.setText(tr("Stop Sweep"))
            self.update_timer.start(50)
            self.module.start_sweep()
        else:
            self.module.stop_sweep()
            self.update_timer.stop()
            self.refresh_plots()
            self.start_btn.setText(tr("Start Sweep"))

    def on_sweep_finished(self):
        self.update_timer.stop()
        self.refresh_plots()
        self.start_btn.setChecked(False)
        self.start_btn.setText(tr("Start Sweep"))

    def on_update_timer(self):
        if self._needs_plot_update:
            self.refresh_plots()
            self._needs_plot_update = False

    def closeEvent(self, event):
        try:
            self.update_timer.stop()
            self.update_timer.timeout.disconnect(self.on_update_timer)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.mag_plot.plotItem.vb.sigResized.disconnect(self.update_coh_views)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.phase_plot.plotItem.vb.sigResized.disconnect(self.update_gd_views)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.mag_plot.plotItem.scene().removeItem(self.coh_view)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.phase_plot.plotItem.scene().removeItem(self.gd_view)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.phase_plot.setXLink(None)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.coh_view.setXLink(None)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.gd_view.setXLink(None)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.update_plot.disconnect(self.update_plot)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.update_ir_plot.disconnect(self.update_ir_plot)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.sweep_finished.disconnect(self.on_sweep_finished)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.progress.disconnect(self.progress_bar.setValue)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.latency_result.disconnect(self.on_latency_result)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.ir_snr_result.disconnect(self.on_ir_snr_result)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.error.disconnect(self.on_error)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        try:
            self.module.signals.harmonics_result.disconnect(self.on_harmonics_result)
        except Exception as e:
            logger.debug(f"Error during cleanup: {e}")
        super().closeEvent(event)

    def update_gd_views(self):
        try:
            if (
                hasattr(self, "gd_view")
                and hasattr(self, "phase_plot")
                and self.gd_view is not None
                and self.phase_plot is not None
            ):
                vb = self.phase_plot.plotItem.vb
                rect = vb.sceneBoundingRect()
                if rect is not None:
                    self.gd_view.setGeometry(rect)
        except (RuntimeError, AttributeError, TypeError):
            pass

    def update_coh_views(self):
        try:
            if (
                hasattr(self, "coh_view")
                and hasattr(self, "mag_plot")
                and self.coh_view is not None
                and self.mag_plot is not None
            ):
                vb = self.mag_plot.plotItem.vb
                rect = vb.sceneBoundingRect()
                if rect is not None:
                    self.coh_view.setGeometry(rect)
        except (RuntimeError, AttributeError, TypeError):
            pass

    def on_ir_snr_result(self, snr):
        self.ir_snr_label.setText(tr("IR SNR: {0:.1f} dB").format(snr))

    def update_plot(self, freq, mag, phase, coh):
        self.freqs.append(freq)
        self.mags.append(mag)
        self.phases.append(phase)
        self.cohs.append(coh)
        self._needs_plot_update = True

    def update_ir_plot(self, time_ms, ir_values):
        self.ir_times_ms = np.asarray(time_ms)
        self.ir_values = np.asarray(ir_values)
        self.ir_curve.setData(self.ir_times_ms, self.ir_values)
        self.etc_times_ms = self.ir_times_ms
        self.etc_db = self._calculate_etc_db(self.ir_values)
        self.refresh_etc_plot()

    def _calculate_etc_db(self, ir_values):
        ir_arr = np.asarray(ir_values, dtype=float)
        if ir_arr.size == 0:
            return np.array([])

        ir_arr = np.nan_to_num(ir_arr, nan=0.0, posinf=0.0, neginf=0.0)
        envelope = np.abs(hilbert(ir_arr))
        peak = np.max(envelope) if envelope.size else 0.0
        if peak <= 1e-12:
            return np.array([])

        etc_db = 20 * np.log10((envelope / peak) + 1e-12)
        return np.clip(etc_db, -120.0, 0.0)

    def _smooth_fractional_octave_values(self, freqs, values, fraction, *, db_values=False, circular_degrees=False):
        if fraction is None or not len(freqs):
            return values

        freqs = np.asarray(freqs, dtype=float)
        values = np.asarray(values, dtype=float)
        valid_freqs = freqs > 0
        if not np.any(valid_freqs):
            return values

        half_width = 2 ** (1 / (2 * fraction))
        smoothed = values.astype(float, copy=True)

        if circular_degrees:
            source_values = np.unwrap(np.radians(values))
        elif db_values:
            source_values = 10 ** (values / 20.0)
        else:
            source_values = values

        for i, freq in enumerate(freqs):
            if freq <= 0:
                continue
            band_mask = valid_freqs & (freqs >= freq / half_width) & (freqs <= freq * half_width)
            if not np.any(band_mask):
                continue
            smoothed[i] = np.mean(source_values[band_mask])

        if circular_degrees:
            smoothed = np.degrees(smoothed)
            return (smoothed + 180) % 360 - 180
        if db_values:
            return 20 * np.log10(smoothed + 1e-12)
        return smoothed

    def _apply_smoothing(self, freqs, mags, phases, fraction, *, db_magnitude=True):
        # Apply fractional-octave smoothing in the display domain; source data remains unchanged.
        if not len(freqs):
            return mags, phases

        if fraction is None:
            return mags, phases

        mags_smooth = self._smooth_fractional_octave_values(freqs, mags, fraction, db_values=db_magnitude)
        phase_smooth = self._smooth_fractional_octave_values(freqs, phases, fraction, circular_degrees=True)

        return mags_smooth, phase_smooth

    def _apply_etc_smoothing(self, etc_db, mode, times_ms=None):
        if not len(etc_db):
            return etc_db

        key = (mode or "off").lower()
        window_ms_map = {
            "light": 0.5,
            "medium": 1.5,
            "heavy": 3.0,
        }
        window_ms = window_ms_map.get(key)
        if window_ms is None:
            return etc_db

        if times_ms is None or len(times_ms) != len(etc_db):
            sample_interval_ms = 1000.0 / float(self.module.audio_engine.sample_rate)
        else:
            times_ms = np.asarray(times_ms, dtype=float)
            deltas = np.diff(times_ms)
            deltas = deltas[deltas > 0]
            if deltas.size == 0:
                return etc_db
            sample_interval_ms = float(np.median(deltas))

        window = max(3, int(round(window_ms / sample_interval_ms)))
        if window % 2 == 0:
            window += 1
        max_len = len(etc_db) if len(etc_db) % 2 == 1 else len(etc_db) - 1
        window = min(window, max_len)
        if window < 3:
            return etc_db

        return np.clip(savgol_filter(etc_db, window_length=window, polyorder=2), -120.0, 0.0)

    def refresh_etc_plot(self):
        if len(self.etc_db) != len(self.etc_times_ms):
            self.etc_curve.clear()
            return

        etc_db = np.asarray(self.etc_db)
        etc_times_ms = np.asarray(self.etc_times_ms)
        if etc_db.size == 0:
            self.etc_curve.clear()
            return

        smooth_mode = self.etc_smooth_combo.currentData()
        self.etc_curve.setData(etc_times_ms, self._apply_etc_smoothing(etc_db, smooth_mode, etc_times_ms))

    def refresh_plots(self):
        if not self.freqs:
            return

        smooth_fraction = self.smooth_combo.currentData()
        unit = self.unit_combo.currentText()

        # Filter data if limit is enabled
        freqs_arr = np.array(self.freqs)
        mags_arr = np.array(self.mags)
        phases_arr = np.array(self.phases)

        # Create mask for filtering
        mask = np.ones(len(freqs_arr), dtype=bool)

        if self.limit_check.isChecked():
            limit = self.limit_spin.value()
            mask &= freqs_arr <= limit

        if self.min_limit_check.isChecked():
            min_limit = self.min_limit_spin.value()
            mask &= freqs_arr >= min_limit

        freqs_to_plot = freqs_arr[mask]
        mags_to_plot = mags_arr[mask]
        phases_to_plot = phases_arr[mask]

        if len(freqs_to_plot) == 0:
            return

        is_transfer_mode = self.module.input_mode in {"XFER", "XFER_REV", "XTALK_LR", "XTALK_RL"}
        is_single_absolute_mode = (not is_transfer_mode) and (self.single_mode_combo.currentData() == "absolute")

        # Base domain:
        # - transfer/relative: gain in dB
        # - single absolute: input level in dBFS(peak)
        if is_single_absolute_mode:
            out_amp_db = 20 * np.log10(self.module.get_output_amplitude() + 1e-12)
            base_db = mags_to_plot + out_amp_db
        else:
            base_db = mags_to_plot

        # Apply Reference
        if self.apply_ref_check.isChecked() and self.module.reference_trace is not None:
            ref = self.module.reference_trace
            if len(ref["freqs"]) > 1:
                interp_mags = np.interp(freqs_to_plot, ref["freqs"], ref["mags"])
                if is_single_absolute_mode:
                    ref_amp = float(ref.get("gen_amp", self.module.amplitude))
                    ref_db = interp_mags + 20 * np.log10(ref_amp + 1e-12)
                    base_db -= ref_db
                else:
                    base_db -= interp_mags

            # Phase Subtraction
            if len(ref["phases"]) > 1:
                interp_phases = np.interp(freqs_to_plot, ref["freqs"], ref["phases"])
                phases_to_plot -= interp_phases
                # Wrap to [-180, 180]
                phases_to_plot = (phases_to_plot + 180) % 360 - 180

        # With reference subtraction, output is always a relative quantity.
        is_effectively_relative = is_transfer_mode or (not is_single_absolute_mode) or self.apply_ref_check.isChecked()
        if is_effectively_relative:
            y_values = base_db
            self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        else:
            mags_linear = 10 ** (base_db / 20)
            try:
                input_sensitivity = self.module.audio_engine.calibration.input_sensitivity
            except Exception:
                input_sensitivity = 1.0

            if unit == "dBFS":
                y_values = base_db
                self.mag_plot.setLabel("left", tr("Magnitude"), units="dBFS")
            elif unit == "dBV":
                y_values = linear_to_amplitude(mags_linear, unit, input_sensitivity)
                self.mag_plot.setLabel("left", tr("Magnitude"), units="dBV")
            elif unit == "dBu":
                y_values = linear_to_amplitude(mags_linear, unit, input_sensitivity)
                self.mag_plot.setLabel("left", tr("Magnitude"), units="dBu")
            elif unit == "Vrms":
                y_values = linear_to_amplitude(mags_linear, unit, input_sensitivity)
                self.mag_plot.setLabel("left", tr("Magnitude"), units="V")
            elif unit == "Vpeak":
                y_values = linear_to_amplitude(mags_linear, unit, input_sensitivity)
                self.mag_plot.setLabel("left", tr("Magnitude"), units="V")
            else:
                y_values = base_db

        is_db_magnitude = is_effectively_relative or unit in {"dBFS", "dBV", "dBu"}
        y_values, phases_to_plot = self._apply_smoothing(
            freqs_to_plot,
            y_values,
            phases_to_plot,
            smooth_fraction,
            db_magnitude=is_db_magnitude,
        )

        self.mag_curve.setData(freqs_to_plot, y_values)
        self.phase_curve.setData(freqs_to_plot, phases_to_plot)

        # RIAA Curve Overlay
        if self.riaa_check.isChecked() and len(freqs_to_plot) > 1:
            riaa_db_ideal = self._calculate_riaa_curve(freqs_to_plot, self.riaa_iec_check.isChecked())

            if self.riaa_mode_combo.currentData() == "auto":
                # Only re-fit if not currently sweeping (to save CPU / avoid jumping)
                if not self.update_timer.isActive():
                    fit_mask = (freqs_to_plot >= 200) & (freqs_to_plot <= 5000)
                    if np.any(fit_mask):
                        offset = np.mean(base_db[fit_mask] - riaa_db_ideal[fit_mask])
                        self._riaa_auto_offset = float(offset)
                        self.riaa_gain_spin.blockSignals(True)
                        self.riaa_gain_spin.setValue(self._riaa_auto_offset)
                        self.riaa_gain_spin.blockSignals(False)
                applied_offset = self._riaa_auto_offset
            else:
                applied_offset = self.riaa_gain_spin.value()

            y_riaa_base = riaa_db_ideal + applied_offset

            if is_effectively_relative:
                y_riaa_final = y_riaa_base
            else:
                mags_riaa_linear = 10 ** (y_riaa_base / 20)
                if unit == "dBFS":
                    y_riaa_final = y_riaa_base
                elif unit in {"dBV", "dBu", "Vrms", "Vpeak"}:
                    y_riaa_final = linear_to_amplitude(mags_riaa_linear, unit, input_sensitivity)
                else:
                    y_riaa_final = y_riaa_base

            self.riaa_curve.setData(freqs_to_plot, y_riaa_final)
        else:
            self.riaa_curve.clear()

        # Group Delay Calculation
        if self.gd_check.isChecked() and len(freqs_to_plot) > 1:
            self.gd_axis.show()

            # Unwrap phase (in degrees) -> radians
            # Note: phases_to_plot might be wrapped to [-180, 180] or relative
            # We should use the raw accumulated phase for GD if possible,
            # but self.phases stores wrapped phase usually?
            # self.phases stores what update_plot sends.
            # In _analyze_tone, it returns degrees in [-180, 180].
            # So we need to unwrap here.

            # Use the raw phases from self.phases, not the potentially modified phases_to_plot
            # But we need to filter them too if we are filtering
            # Actually phases_to_plot IS filtered above.
            # But wait, the original code used self.phases (raw) here.
            # If we want raw phases but filtered, we should use the filtered raw phases.
            # Let's re-extract raw filtered phases if needed, or just use phases_to_plot if that's what we want.
            # The comment says "Use the raw phases from self.phases".
            # So we should use the filtered version of self.phases.
            # We already have phases_to_plot which is filtered self.phases (before ref subtraction).
            # Wait, phases_to_plot is modified by ref subtraction in lines 925.
            # So we need a clean filtered raw phase.

            # If reference is applied, we should probably calculate GD of the *corrected* phase?
            # Yes, Group Delay of the system as displayed.
            # So use phases_to_plot (which includes ref subtraction).

            # Unwrap requires radians usually, or we can just unwrap degrees with period 360
            phases_rad = np.radians(phases_to_plot)
            phases_unwrapped = np.unwrap(phases_rad)

            # dPhi / dOmega
            # dOmega = 2 * pi * dF
            # GD = - dPhi / dOmega

            # Calculate derivative
            d_phi = np.diff(phases_unwrapped)
            d_freq = np.diff(freqs_to_plot)

            # Avoid div by zero
            d_freq[d_freq == 0] = 1e-12

            group_delay_sec = -d_phi / (2 * np.pi * d_freq)

            # Plot against mid-points of freqs
            freq_mids = (freqs_to_plot[:-1] + freqs_to_plot[1:]) / 2

            # Manually log X for the overlay view
            log_freq_mids = np.log10(freq_mids)

            self.gd_curve.setData(log_freq_mids, group_delay_sec)
            self.gd_view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            self.update_gd_views()

        else:
            self.gd_axis.hide()
            self.gd_curve.clear()

        # Coherence (valid only in transfer modes)
        if (
            is_transfer_mode
            and self.coh_check.isChecked()
            and len(freqs_to_plot) > 1
            and len(self.cohs) == len(self.freqs)
        ):
            self.coh_axis.show()
            cohs_arr = np.array(self.cohs)
            cohs_to_plot = cohs_arr[mask]

            cohs_to_plot = self._smooth_fractional_octave_values(freqs_to_plot, cohs_to_plot, smooth_fraction)
            cohs_to_plot = np.clip(cohs_to_plot, 0, 1)

            log_freqs = np.log10(freqs_to_plot)
            self.coh_curve.setData(log_freqs, cohs_to_plot)
            self.update_coh_views()
        else:
            self.coh_axis.hide()
            self.coh_curve.clear()

        self.refresh_harmonics_plot()

    def on_harmonics_as_percent_toggled(self, checked):
        y_axis = self.harmonics_plot.getPlotItem().getAxis("left")
        if checked:
            self.harmonics_plot.setLogMode(x=True, y=True)
            self.harmonics_plot.setYRange(np.log10(0.0001), np.log10(100))
            percent_ticks = [100, 10, 1, 0.1, 0.01, 0.001, 0.0001]
            ticks_log = [(np.log10(t), f"{t:g}%") for t in percent_ticks]
            y_axis.setTicks([ticks_log])
        else:
            self.harmonics_plot.setLogMode(x=True, y=False)
            y_axis.setTicks(None)
            self.harmonics_plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
        self.refresh_harmonics_plot()

    def on_harmonics_result(self, data):
        self.harmonics_data = data
        self.refresh_harmonics_plot()

    def refresh_harmonics_plot(self):
        if not self.harmonics_data:
            for curve in self.h_curves.values():
                curve.clear()
            return

        freqs_arr = np.asarray(self.harmonics_data["freqs"])
        if len(freqs_arr) == 0:
            for curve in self.h_curves.values():
                curve.clear()
            return

        # Filtering mask
        mask = np.ones(len(freqs_arr), dtype=bool)
        if self.limit_check.isChecked():
            limit = self.limit_spin.value()
            mask &= freqs_arr <= limit
        if self.min_limit_check.isChecked():
            min_limit = self.min_limit_spin.value()
            mask &= freqs_arr >= min_limit

        freqs_to_plot = freqs_arr[mask]
        if len(freqs_to_plot) == 0:
            for curve in self.h_curves.values():
                curve.clear()
            return

        is_transfer_mode = self.module.input_mode in {"XFER", "XFER_REV", "XTALK_LR", "XTALK_RL"}
        is_single_absolute_mode = (not is_transfer_mode) and (self.single_mode_combo.currentData() == "absolute")
        smooth_fraction = self.smooth_combo.currentData()
        unit = self.unit_combo.currentText()

        # Determine effective relativity and label
        is_effectively_relative = is_transfer_mode or (not is_single_absolute_mode) or self.apply_ref_check.isChecked()

        if self.harmonics_as_percent_check.isChecked():
            self.harmonics_plot.setLabel("left", tr("Distortion"), units="%")
        elif is_effectively_relative:
            self.harmonics_plot.setLabel("left", tr("Level"), units="dB")
        else:
            if unit == "dBFS":
                self.harmonics_plot.setLabel("left", tr("Level"), units="dBFS")
            elif unit == "dBV":
                self.harmonics_plot.setLabel("left", tr("Level"), units="dBV")
            elif unit == "dBu":
                self.harmonics_plot.setLabel("left", tr("Level"), units="dBu")
            elif unit in {"Vrms", "Vpeak"}:
                self.harmonics_plot.setLabel("left", tr("Level"), units="V")

        visibility_mapping = {
            "fundamental": self.show_fundamental_check.isChecked(),
            "h2": self.show_h2_check.isChecked(),
            "h3": self.show_h3_check.isChecked(),
            "h4": self.show_h4_check.isChecked(),
            "h5": self.show_h5_check.isChecked(),
            "thd": self.show_thd_check.isChecked(),
        }

        # Get raw data for each key
        raw_db_dict = {}
        for key in ("fundamental", "h2", "h3", "h4", "h5", "thd"):
            if key in self.harmonics_data:
                raw_db_dict[key] = np.asarray(self.harmonics_data[key])[mask]
            else:
                raw_db_dict[key] = np.full_like(freqs_arr[mask], -120.0)

        for key in ("fundamental", "h2", "h3", "h4", "h5", "thd"):
            curve = self.h_curves[key]
            if not visibility_mapping[key]:
                curve.clear()
                continue

            # Calculate base dB
            if is_single_absolute_mode:
                out_amp_db = 20 * np.log10(self.module.get_output_amplitude() + 1e-12)
                base_db = raw_db_dict[key] + out_amp_db
            else:
                base_db = raw_db_dict[key]

            # Apply reference
            if self.apply_ref_check.isChecked() and self.module.reference_trace is not None:
                ref = self.module.reference_trace
                if len(ref["freqs"]) > 1:
                    interp_mags = np.interp(freqs_to_plot, ref["freqs"], ref["mags"])
                    if is_single_absolute_mode:
                        ref_amp = float(ref.get("gen_amp", self.module.amplitude))
                        ref_db = interp_mags + 20 * np.log10(ref_amp + 1e-12)
                        base_db -= ref_db
                    else:
                        base_db -= interp_mags

            # Unit conversion
            if self.harmonics_as_percent_check.isChecked():
                # Percent is relative to the fundamental
                ratio = 10 ** ((raw_db_dict[key] - raw_db_dict["fundamental"]) / 20.0)
                y_values = np.clip(100.0 * ratio, 1e-6, None)
            elif is_effectively_relative:
                y_values = base_db
            else:
                mags_linear = 10 ** (base_db / 20)
                try:
                    input_sensitivity = self.module.audio_engine.calibration.input_sensitivity
                except Exception:
                    input_sensitivity = 1.0

                if unit == "dBFS":
                    y_values = base_db
                elif unit in {"dBV", "dBu", "Vrms", "Vpeak"}:
                    y_values = linear_to_amplitude(mags_linear, unit, input_sensitivity)
                else:
                    y_values = base_db

            # Apply smoothing
            if self.harmonics_as_percent_check.isChecked():
                is_db_magnitude = False
            else:
                is_db_magnitude = is_effectively_relative or unit in {"dBFS", "dBV", "dBu"}

            if smooth_fraction is not None:
                y_values = self._smooth_fractional_octave_values(
                    freqs_to_plot,
                    y_values,
                    smooth_fraction,
                    db_values=is_db_magnitude,
                )

            curve.setData(freqs_to_plot, y_values)
