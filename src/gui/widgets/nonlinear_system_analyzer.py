import logging
import threading
import time
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
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
    windows,
    fftconvolve,
    coherence,
    savgol_filter,
)

from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.gui.widgets.comparable_interface import ComparableWidgetInterface

logger = logging.getLogger(__name__)


class NonlinearSystemAnalyzerSignals(QObject):
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


class NonlinearSystemAnalyzer(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.signals = NonlinearSystemAnalyzerSignals()

        # Sweep Parameters
        self.start_freq = 20.0
        self.end_freq = 20000.0
        self.sweep_duration = 3.0  # seconds
        self.amplitude_db = -6.0  # dBFS (peak)
        self.averages = 2  # TSA (Time Synchronized Averaging) count
        self.num_amplitudes = 5  # Number of amplitude steps for PHM (typically 5 to 7 steps)
        self.latency_sec = 0.0

        # Routing Config
        self.output_channel = "STEREO"  # 'L', 'R', 'STEREO'
        self.input_mode = "XFER"  # 'L' (Single Ch), 'XFER' (2-Ch relative)
        self.ref_channel_index = 0
        self.meas_channel_index = 1

        self.worker = None
        self.cal_worker = None
        self._dummy_callback_id = None
        self.signals.sweep_finished.connect(self._cleanup_dummy_callback)

    @property
    def name(self) -> str:
        return "Nonlinear System Analyzer"

    @property
    def description(self) -> str:
        return "Extracts true linear response and 2nd-5th harmonics using SSS and Parallel Hammerstein modeling."

    def get_widget(self):
        return NonlinearSystemAnalyzerWidget(self)

    def _dummy_callback(self, indata, outdata, frames, time, status):
        pass

    def _cleanup_dummy_callback(self):
        if self._dummy_callback_id is not None:
            self.audio_engine.unregister_callback(self._dummy_callback_id)
            self._dummy_callback_id = None

    def run_play_rec(self, output_data, input_channels=2):
        session = PlayRecSession(self.audio_engine, output_data, input_channels)
        session.start()
        expected_duration = len(output_data) / self.audio_engine.sample_rate
        session.wait(timeout=expected_duration + 2.0)
        session.stop()
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

        # Calculate cross-correlation to find peak delay
        correlation = fftconvolve(recorded, np.flip(chirp), mode="full")
        lag = np.argmax(np.abs(correlation)) - len(chirp) + 1

        self.latency_sec = max(0.0, lag / sample_rate)
        self.signals.latency_result.emit(self.latency_sec)
        logger.info(f"Calibration successful: Latency = {self.latency_sec * 1000:.2f} ms ({lag} samples)")

    def _generate_sss_and_inverse(self, sample_rate, amplitude):
        """
        Generates Synchronized Sine Sweep (SSS) signal and its analytical inverse filter.
        Ensures strict mathematical phase relationships to capture unaliased harmonics.
        Includes frequency margins (guard bands) to push window-taper noise outside the target band.
        """
        num_samples = int(sample_rate * self.sweep_duration)
        t = np.linspace(0, self.sweep_duration, num_samples, endpoint=False)

        # Add frequency guard bands (margins) to keep the target band (start_freq to end_freq) flat.
        start_margin = max(2.0, self.start_freq / 1.3)
        nyquist = sample_rate / 2.0
        end_margin = min(nyquist * 0.95, self.end_freq * 1.15)

        w1 = 2 * np.pi * start_margin
        T = self.sweep_duration
        L = np.log(end_margin / start_margin)

        # SSS Phase Design
        phase = (w1 * T / L) * (np.exp(t * L / T) - 1)
        sss_signal = amplitude * np.sin(phase)

        # Tukey window to minimize transient clicks at start and end
        window = windows.tukey(num_samples, alpha=0.02)
        sss_signal *= window

        # Analytical inverse filter (ESS/SSS Match-filter deconvolution)
        # Apply amplitude correction (6dB/octave slope)
        inv_envelope = np.exp(t * L / T)
        inverse_filter = inv_envelope * np.sin(phase)
        inverse_filter *= window
        inverse_filter = np.flip(inverse_filter)

        # Normalize the inverse filter so that the peak of the direct convolution is 1
        direct_conv = fftconvolve(sss_signal, inverse_filter, mode="full")
        peak = np.max(np.abs(direct_conv))
        if peak > 1e-12:
            inverse_filter /= peak

        return sss_signal, inverse_filter

    def _execute_measurement(self, worker):
        sample_rate = self.audio_engine.sample_rate
        P = 5  # We support up to P=5 orders (Fundamental, 2nd, 3rd, 4th, 5th harmonics)

        # 1. Define Amplitude Scanning Range (in linear scale)
        # Scan from self.amplitude_db down by steps of 4dB or 6dB to cover linear dependency.
        max_amp = 10 ** (self.amplitude_db / 20)
        # Step down to cover sufficient dynamic range. 5 steps: e.g. [0.25, 0.43, 0.62, 0.81, 1.0] * max_amp
        amplitudes = np.linspace(0.2, 1.0, self.num_amplitudes) * max_amp

        logger.info(f"Starting SSS/PHM measurement. Scanned amplitudes (linear): {amplitudes}")

        # Dictionary to store measured impulse responses for each amplitude level
        # Key: amplitude level index, Value: np.array of impulse responses
        responses_ref = []  # reference channel (XFER mode)
        responses_meas = []  # measurement channel

        # Total sweeps to run
        total_sweeps = self.num_amplitudes * self.averages
        sweep_counter = 0

        # Helper to pad output and run PlayRec
        padding_samples = int(0.5 * sample_rate)  # 500ms tail padding

        for amp_idx, amp in enumerate(amplitudes):
            if not worker.is_running:
                return

            # Generate SSS signal and match inverse filter for this amplitude
            sss, inv_filter = self._generate_sss_and_inverse(sample_rate, amp)
            out_signal = np.concatenate([sss, np.zeros(padding_samples)])

            # Router output allocation
            out_data = np.zeros((len(out_signal), 2), dtype=np.float32)
            if self.output_channel in {"L", "STEREO"}:
                out_data[:, 0] = out_signal
            if self.output_channel in {"R", "STEREO"}:
                out_data[:, 1] = out_signal

            # Time Synchronized Averaging (TSA) buffers
            accum_data = None
            ref_peak_idx = None

            for avg in range(self.averages):
                if not worker.is_running:
                    return

                # Record
                rec_data = self.run_play_rec(out_data, input_channels=2)

                # Real-world OS hardware delay jitter alignment
                # Align based on the measurement channel (or channel 0 if single)
                align_sig = rec_data[:, self.meas_channel_index if rec_data.shape[1] > 1 else 0]
                temp_ir = fftconvolve(align_sig, inv_filter, mode="full")
                peak_idx = np.argmax(np.abs(temp_ir))

                if accum_data is None:
                    accum_data = rec_data
                    ref_peak_idx = peak_idx
                else:
                    # Align other averages to sample level
                    shift = ref_peak_idx - peak_idx
                    shifted = np.roll(rec_data, shift, axis=0)
                    if shift > 0:
                        shifted[:shift, :] = 0
                    elif shift < 0:
                        shifted[shift:, :] = 0
                    accum_data += shifted

                sweep_counter += 1
                progress_pct = int(90 * (sweep_counter / total_sweeps))
                self.signals.progress.emit(progress_pct)

            # TSA Averaged data for this amplitude level
            averaged_data = accum_data / self.averages

            # Execute Offline Mode/Virtual Loopback emulation if active
            if getattr(self.audio_engine, "offline_mode", False):
                # Simulate a nonlinear physical system (e.g. static cubic clipping + 1st order lowpass)
                # output = x - 0.1 * x^2 + 0.15 * x^3 - 0.05 * x^4 + 0.08 * x^5
                x_ref = averaged_data[:, self.ref_channel_index]
                # Apply simulated non-linear system transfer
                simulated_meas = sss.copy()
                # Apply harmonics
                simulated_meas = (
                    simulated_meas
                    - 0.08 * (simulated_meas ** 2)
                    + 0.12 * (simulated_meas ** 3)
                    - 0.04 * (simulated_meas ** 4)
                    + 0.06 * (simulated_meas ** 5)
                )
                # Pad to match recording size
                simulated_meas = np.concatenate([simulated_meas, np.zeros(padding_samples)])
                averaged_data[:, self.meas_channel_index] = simulated_meas
                averaged_data[:, self.ref_channel_index] = np.concatenate([sss, np.zeros(padding_samples)])

            # Deconvolution to get raw impulse responses g_k(t)
            sig_ref = averaged_data[:, self.ref_channel_index]
            sig_meas = averaged_data[:, self.meas_channel_index]

            ir_ref_raw = fftconvolve(sig_ref, inv_filter, mode="full")
            ir_meas_raw = fftconvolve(sig_meas, inv_filter, mode="full")

            # Peak capture time-gate to isolate system response from tail noise
            gate_pre = int(0.005 * sample_rate)  # 5ms before peak
            gate_post = int(0.4 * sample_rate)   # 400ms after peak (enables low-frequency response)
            
            # Use measurement peak index as the center of gravity
            meas_peak = np.argmax(np.abs(ir_meas_raw))
            start_gate = max(0, meas_peak - gate_pre)
            end_gate = min(len(ir_meas_raw), meas_peak + gate_post)
            gate_length = end_gate - start_gate

            # Truncate and Tukey-window responses
            win = windows.tukey(gate_length, alpha=0.05)
            ir_ref_win = ir_ref_raw[start_gate:end_gate] * win
            ir_meas_win = ir_meas_raw[start_gate:end_gate] * win

            # Save the windowed raw impulse responses
            responses_ref.append(ir_ref_win)
            responses_meas.append(ir_meas_win)

        # 2. Parallel Hammerstein Kernels (PHM) Separation using Chebyshev Polynomial Inversion
        #
        # Model: g_k(t) = sum_{p=1}^P M_{k, p} * h_p(t)
        # Where: M_{k, p} = T_p(v_k) is the p-th Chebyshev polynomial evaluated at scaled amplitude v_k.
        # Chebyshev Polynomials (evaluated in normalized range [-1.0, 1.0]):
        # T_1(v) = v
        # T_2(v) = 2v^2 - 1
        # T_3(v) = 4v^3 - 3v
        # T_4(v) = 8v^4 - 8v^2 + 1
        # T_5(v) = 16v^5 - 20v^3 + 5v
        
        # Normalize amplitudes to range [0.1, 1.0] based on the maximum excitation amplitude
        norm_v = amplitudes / max_amp

        # Construct translation matrix M
        # Shape: (num_amplitudes, P)
        M = np.zeros((self.num_amplitudes, P))
        for k in range(self.num_amplitudes):
            v = norm_v[k]
            M[k, 0] = v                              # T1
            M[k, 1] = 2 * (v ** 2) - 1               # T2
            M[k, 2] = 4 * (v ** 3) - 3 * v           # T3
            M[k, 3] = 8 * (v ** 4) - 8 * (v ** 2) + 1 # T4
            M[k, 4] = 16 * (v ** 5) - 20 * (v ** 3) + 5 * v # T5

        # Compute Pseudo-Inverse of Matrix M
        M_pinv = np.linalg.pinv(M)  # Shape: (P, num_amplitudes)

        # We will separate the Hammerstein kernels h_p(t) at each time sample.
        # Shape of each g_k is gate_length.
        gate_length = len(responses_meas[0])
        
        # h_kernels[p] will store the p-th Hammerstein kernel in time-domain
        h_kernels_meas = np.zeros((P, gate_length))
        h_kernels_ref = np.zeros((P, gate_length))

        for t in range(gate_length):
            # Vector of responses at time t for all amplitudes
            g_t_meas = np.array([responses_meas[k][t] for k in range(self.num_amplitudes)])
            g_t_ref = np.array([responses_ref[k][t] for k in range(self.num_amplitudes)])

            # Matrix multiplication to separate kernels: h(t) = M_pinv * g(t)
            h_kernels_meas[:, t] = np.dot(M_pinv, g_t_meas)
            h_kernels_ref[:, t] = np.dot(M_pinv, g_t_ref)

        # 3. Frequency Analysis and Relative XFER Normalization
        # Calculate FFTs of separated Hammerstein Kernels
        H_meas_list = []
        H_ref_list = []

        for p in range(P):
            # Measure
            H_meas = fft_manager.rfft(h_kernels_meas[p])
            H_meas_list.append(H_meas)
            # Reference
            H_ref = fft_manager.rfft(h_kernels_ref[p])
            H_ref_list.append(H_ref)

        freqs = fft_manager.rfftfreq(gate_length, d=1 / sample_rate)

        # Target Frequency Grid Mask
        mask = (freqs >= self.start_freq) & (freqs <= self.end_freq)
        valid_freqs = freqs[mask]

        # Containers to emit
        magnitudes_db_dict = {}
        phases_deg_dict = {}

        # Separation and relative conversion
        for p in range(P):
            h_key = f"h{p+1}"  # 'h1' = Fundamental, 'h2' = 2nd Harmonic, etc.
            
            H_meas_p = H_meas_list[p]
            H_ref_p = H_ref_list[p]

            if self.input_mode == "XFER":
                # Relative 2-Channel XFER transfer function: normalize by reference channel
                # Apply Tikhonov regularization to prevent division-by-zero noise spikes at frequency extremes.
                # Use a small regularization factor (-60dB relative to peak reference power).
                ref_power = np.abs(H_ref_p) ** 2
                peak_ref_power = np.max(ref_power)
                alpha = peak_ref_power * 1e-6 + 1e-12
                with np.errstate(divide="ignore", invalid="ignore"):
                    H_xfer = (H_meas_p * np.conj(H_ref_p)) / (ref_power + alpha)
                    H_xfer = np.nan_to_num(H_xfer)
                valid_H = H_xfer[mask]
            else:
                # Single Channel Mode: 1-channel response
                valid_H = H_meas_p[mask]

                # Compensation for physical loopback latency (avoid wrap phase plots)
                delay_samples = int(self.latency_sec * sample_rate)
                phase_correction = 2 * np.pi * valid_freqs * (delay_samples / sample_rate)
                
                # Apply correction to the complex frequency representation
                valid_H = valid_H * np.exp(1j * phase_correction)

            # Compute Gain and Phase
            mag_db = 20 * np.log10(np.abs(valid_H) + 1e-12)
            phase_rad = np.unwrap(np.angle(valid_H))
            phase_deg = np.degrees(phase_rad)
            # Wrap phase to standard range [-180, 180]
            phase_deg = (phase_deg + 180) % 360 - 180

            magnitudes_db_dict[h_key] = mag_db
            phases_deg_dict[h_key] = phase_deg

        # Post-Processing: Normalize fundamental linear response (h1) near 0dB if in loopback
        # This makes plots highly intuitive for loopback cables.
        if self.input_mode == "XFER":
            # The XFER relative mode is naturally normalized close to 0dB.
            pass

        self.signals.progress.emit(95)

        # 4. Prepare Time-Domain Kernel display
        # Generate time axis in milliseconds centered around system peak
        # Center peak index
        p1_peak = np.argmax(np.abs(h_kernels_meas[0]))
        # We display +/- 50ms region around the peak
        disp_pre = min(p1_peak, int(0.01 * sample_rate))  # 10ms pre-trigger
        disp_post = min(gate_length - p1_peak, int(0.09 * sample_rate)) # 90ms post-trigger
        
        t_indices = np.arange(p1_peak - disp_pre, p1_peak + disp_post)
        time_ms = (t_indices - p1_peak) / sample_rate * 1000.0

        separated_kernels_data = []
        for p in range(P):
            # Normalize display for visual clarity
            kernel_slice = h_kernels_meas[p][t_indices]
            # Max amplitude of first kernel as reference to keep proportional size
            ref_max = np.max(np.abs(h_kernels_meas[0]))
            if ref_max > 1e-12:
                kernel_slice = kernel_slice / ref_max
            separated_kernels_data.append(kernel_slice)

        # Emit plots
        self.signals.update_plot.emit(valid_freqs, magnitudes_db_dict, phases_deg_dict)
        self.signals.update_kernels.emit(time_ms, separated_kernels_data)
        self.signals.progress.emit(100)


class NonlinearSystemAnalyzerWidget(QWidget, ComparableWidgetInterface):
    def __init__(self, module: NonlinearSystemAnalyzer):
        QWidget.__init__(self)
        ComparableWidgetInterface.__init__(self)
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

    def init_ui(self):
        # Premium layout design
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # --- Sidebar Container (Left Side, Fixed Width) ---
        sidebar_container = QWidget()
        sidebar_container.setFixedWidth(260)
        sidebar_main_layout = QVBoxLayout(sidebar_container)
        sidebar_main_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_main_layout.setSpacing(10)

        # Module Header Info (Experimental Badge)
        badge_layout = QHBoxLayout()
        badge_title = QLabel(f"<b>{tr('Nonlinear System Analyzer')}</b>")
        badge_label = QLabel(tr("Experimental"))
        badge_label.setStyleSheet(
            "background-color: #d9534f; color: white; border-radius: 4px; padding: 2px 5px; font-size: 10px; font-weight: bold;"
        )
        badge_layout.addWidget(badge_title)
        badge_layout.addWidget(badge_label)
        sidebar_main_layout.addLayout(badge_layout)

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
        sweep_group = QGroupBox(tr("SSS Parameters"))
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
        sweep_form.addRow(tr("TSA Averages:"), self.tsa_spin)

        scroll_layout.addWidget(sweep_group)

        # Group 2: Parallel Hammerstein Model Parameters
        phm_group = QGroupBox(tr("Hammerstein Modeling"))
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
        phm_form.addRow(tr("Amp Scans (P=5):"), self.steps_spin)

        self.smooth_combo = QComboBox()
        self.smooth_combo.addItem(tr("None"), "None")
        self.smooth_combo.addItem(tr("Light (Savitzky-Golay)"), "Light")
        self.smooth_combo.addItem(tr("Medium (Savitzky-Golay)"), "Medium")
        self.smooth_combo.addItem(tr("Heavy (Savitzky-Golay)"), "Heavy")
        self.smooth_combo.setCurrentIndex(1)  # Default: Light
        self.smooth_combo.currentIndexChanged.connect(self.refresh_plots_with_smoothing)
        phm_form.addRow(tr("Display Smoothing:"), self.smooth_combo)

        scroll_layout.addWidget(phm_group)

        # Group 3: Routing & Calibration
        route_group = QGroupBox(tr("Routing & Calibration"))
        route_form = QFormLayout(route_group)
        route_form.setContentsMargins(6, 8, 6, 8)
        route_form.setSpacing(6)

        self.in_mode_combo = QComboBox()
        self.in_mode_combo.addItem(tr("XFER (Ref=L, Meas=R)"), "XFER")
        self.in_mode_combo.addItem(tr("1-Ch Mode (L)"), "L")
        self.in_mode_combo.setCurrentIndex(0)
        self.in_mode_combo.currentIndexChanged.connect(self.on_routing_changed)
        route_form.addRow(tr("Input Mode:"), self.in_mode_combo)

        # Latency Display
        self.latency_label = QLabel("0.00 ms")
        self.latency_label.setStyleSheet("font-weight: bold; color: #4ba3e3;")
        route_form.addRow(tr("Latency:"), self.latency_label)

        # Calibrate Button
        self.cal_btn = QPushButton(tr("Calibrate Delay"))
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

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        ctrl_main_layout.addWidget(self.progress_bar)

        sidebar_main_layout.addWidget(ctrl_container)
        main_layout.addWidget(sidebar_container)

        # --- Plot Content Area (Right Side, Tab Widget) ---
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMinimumHeight(450)
        
        # Tab 1: Magnitude Response (Bode Plot)
        self.mag_tab = QWidget()
        mag_layout = QVBoxLayout(self.mag_tab)
        self.mag_plot = pg.PlotWidget(title=tr("Bode Magnitude Response (PHM Separation)"))
        self.mag_plot.setLabel("left", tr("Gain"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(True, False)
        self.mag_plot.showGrid(True, True, alpha=0.3)
        mag_layout.addWidget(self.mag_plot)
        self.plot_tabs.addTab(self.mag_tab, tr("Bode Magnitude"))

        # Tab 2: Phase Response
        self.phase_tab = QWidget()
        phase_layout = QVBoxLayout(self.phase_tab)
        self.phase_plot = pg.PlotWidget(title=tr("Bode Phase Response (PHM Separation)"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(True, False)
        self.phase_plot.showGrid(True, True, alpha=0.3)
        phase_layout.addWidget(self.phase_plot)
        self.plot_tabs.addTab(self.phase_tab, tr("Bode Phase"))

        # Tab 3: Time Domain Kernels h_p(t)
        self.kernel_tab = QWidget()
        kernel_layout = QVBoxLayout(self.kernel_tab)
        self.kernel_plot = pg.PlotWidget(title=tr("Separated Parallel Hammerstein Kernels"))
        self.kernel_plot.setLabel("left", tr("Normalized Amplitude"))
        self.kernel_plot.setLabel("bottom", tr("Time"), units="ms")
        self.kernel_plot.showGrid(True, True, alpha=0.3)
        kernel_layout.addWidget(self.kernel_plot)
        self.plot_tabs.addTab(self.kernel_tab, tr("Hammerstein Kernels"))

        # Premium Plot Legends
        self.mag_plot.addLegend(offset=(10, 10))
        self.phase_plot.addLegend(offset=(10, 10))
        self.kernel_plot.addLegend(offset=(10, 10))

        main_layout.addWidget(self.plot_tabs, stretch=1)

    def on_routing_changed(self):
        mode = self.in_mode_combo.currentData()
        self.module.input_mode = mode
        # Disable calibrate button for XFER mode since delay is automatically canceled
        self.cal_btn.setEnabled(mode == "L")

    def start_measurement(self):
        # Turn off main audio engine stream if running to capture hardware exclusively
        if self.module.audio_engine.stream and self.module.audio_engine.stream.active:
            self.module.audio_engine.stop_stream()

        self.start_btn.setEnabled(False)
        self.cal_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)

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
        self.cal_btn.setEnabled(self.module.input_mode == "L")
        self.stop_btn.setEnabled(False)

    def on_latency_result(self, val):
        self.latency_label.setText(f"{val * 1000:.2f} ms")
        QMessageBox.information(
            self,
            tr("Calibration Successful"),
            tr("Measured loopback delay: {0:.2f} ms").format(val * 1000)
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

        # Retrieve current display smoothing level
        smooth_level = self.smooth_combo.currentData()

        # Premium Palette
        # h1: Light blue, h2: Green, h3: Amber/Orange, h4: Magenta/Pink, h5: Crimson Red
        colors = {
            "h1": (75, 163, 227),    # #4ba3e3
            "h2": (43, 140, 86),     # #2b8c56
            "h3": (230, 140, 20),    # #e68c14
            "h4": (200, 50, 160),    # #c832a0
            "h5": (217, 83, 79),     # #d9534f
        }
        
        labels = {
            "h1": tr("Fundamental (Linear h1)"),
            "h2": tr("2nd Harmonic (h2)"),
            "h3": tr("3rd Harmonic (h3)"),
            "h4": tr("4th Harmonic (h4)"),
            "h5": tr("5th Harmonic (h5)"),
        }

        # Clear existing curves before redrawing
        self.mag_plot.clear()
        self.phase_plot.clear()

        for key in ["h1", "h2", "h3", "h4", "h5"]:
            if key in magnitudes_db_dict:
                # Apply Savitzky-Golay Smoothing
                mag_smoothed = self.apply_smoothing(magnitudes_db_dict[key], smooth_level)
                phase_smoothed = self.apply_smoothing(phases_deg_dict[key], smooth_level)

                # Magnitude Plot
                pen_mag = pg.mkPen(color=colors[key], width=2)
                self.mag_plot.plot(
                    freqs,
                    mag_smoothed,
                    pen=pen_mag,
                    name=labels[key]
                )

                # Phase Plot
                pen_phase = pg.mkPen(color=colors[key], width=1.5, style=Qt.PenStyle.SolidLine)
                self.phase_plot.plot(
                    freqs,
                    phase_smoothed,
                    pen=pen_phase,
                    name=labels[key]
                )

    def on_update_kernels(self, time_ms, separated_kernels_data):
        self.kernel_plot.clear()
        
        # Auto-fit the X Range to focus on the impulse peak details (-5ms to +35ms)
        self.kernel_plot.setXRange(-5.0, 35.0)

        colors = [
            (75, 163, 227),  # h1
            (43, 140, 86),   # h2
            (230, 140, 20),  # h3
            (200, 50, 160),  # h4
            (217, 83, 79),   # h5
        ]

        labels = [
            tr("Kernel h1"),
            tr("Kernel h2"),
            tr("Kernel h3"),
            tr("Kernel h4"),
            tr("Kernel h5"),
        ]

        for p in range(len(separated_kernels_data)):
            pen = pg.mkPen(color=colors[p], width=1.8)
            self.kernel_plot.plot(
                time_ms,
                separated_kernels_data[p],
                pen=pen,
                name=labels[p]
            )

    # --- ComparableWidgetInterface ---
    def get_comparison_data(self):
        # Implements ComparableWidgetInterface for data overlay and save comparison traces
        if self.cached_freqs is None or "h1" not in self.cached_mags:
            return None
        
        # We export the primary fundamental response (h1) as the default comparison trace
        return {
            "x": self.cached_freqs,
            "y": self.cached_mags["h1"],
            "title": f"PHM Fundamental (h1) Sweep - {time.strftime('%H:%M:%S')}",
            "x_label": "Frequency",
            "x_units": "Hz",
            "y_label": "Gain",
            "y_units": "dB",
        }
