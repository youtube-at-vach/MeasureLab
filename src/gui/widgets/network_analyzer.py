
import threading

import numpy as np
import pyqtgraph as pg
from scipy.signal import chirp as signal_chirp, coherence, correlate, correlation_lags, fftconvolve, savgol_filter, windows
from PyQt6.QtCore import QObject, QThread, pyqtSignal
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

from src.core.audio_engine import AudioEngine
from src.core.fft_manager import fft_manager
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.utils import amplitude_to_linear, linear_to_amplitude


class NetworkAnalyzerSignals(QObject):
    update_plot = pyqtSignal(float, float, float, float)  # freq, mag_db, phase_deg, coherence
    sweep_finished = pyqtSignal()
    progress = pyqtSignal(int)
    latency_result = pyqtSignal(float)
    ir_snr_result = pyqtSignal(float)
    error = pyqtSignal(str)


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

    def stop(self):
        if self.callback_id is not None:
            self.audio_engine.unregister_callback(self.callback_id)
            self.callback_id = None

    def wait(self, timeout=None):
        return self.completion_event.wait(timeout)

    def _callback(self, indata, outdata, frames, time, status):
        with self.lock:
            if self.is_complete:
                outdata.fill(0)
                return

            remaining = self.total_frames - self.current_frame
            chunk = min(frames, remaining)

            # Output
            outdata[:chunk, :] = self.output_data[self.current_frame : self.current_frame + chunk, :]
            if chunk < frames:
                outdata[chunk:, :] = 0

            # Input
            if indata.shape[1] > 0:
                # Capture requested number of channels
                ch_to_copy = min(self.input_channels, indata.shape[1])
                self.input_data[self.current_frame : self.current_frame + chunk, :ch_to_copy] = indata[
                    :chunk, :ch_to_copy
                ]

            self.current_frame += chunk

            if self.current_frame >= self.total_frames:
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
        self.end_freq = 24000.0
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
        self.chirp_duration = 1.0
        self.averages = 1

        self.worker = None
        self.calibration_worker = None

        self.reference_trace = None

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
        session.wait()
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

            print("Playing chirp for latency calibration...")

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
            print(f"Measured Latency: {self.latency_sec * 1000:.2f} ms")

        except Exception as e:
            self.signals.error.emit(f"Calibration failed: {e}")

    def start_sweep(self):
        if self.worker and self.worker.isRunning():
            return
        self.worker = FastSweepWorker(self)
        self.worker.start()

    def start_calibration(self):
        if self.calibration_worker and self.calibration_worker.isRunning():
            return
        self.calibration_worker = CalibrationWorker(self)
        self.calibration_worker.start()

    def stop_sweep(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()

    def _prepare_output_buffer(self, signal):
        """Prepares stereo output buffer based on routing."""
        out_data = np.zeros((len(signal), 2), dtype=np.float32)
        if self.output_channel in ["L", "STEREO"]:
            out_data[:, 0] = signal
        if self.output_channel in ["R", "STEREO"]:
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
        if self.input_mode in ["XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"]:
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

    def _process_sweep_data(self, rec_data, inv_filter, chirp, sample_rate, worker):
        """Processes the recorded sweep data to calculate magnitude and phase response, IR SNR, and Coherence."""
        def get_ir(signal):
            return fftconvolve(signal, inv_filter, mode="full")

        ir_snr_db = None

        if self.input_mode in ["XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"]:
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

        if ir_snr_db is not None:
            self.signals.ir_snr_result.emit(ir_snr_db)

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
        self.module.signals.sweep_finished.connect(self.on_sweep_finished)
        self.module.signals.progress.connect(self.progress_bar.setValue)
        self.module.signals.latency_result.connect(self.on_latency_result)
        self.module.signals.ir_snr_result.connect(self.on_ir_snr_result)
        self.module.signals.error.connect(self.on_error)

        self.freqs = []
        self.mags = []
        self.phases = []
        self.cohs = []

    def init_ui(self):
        layout = QHBoxLayout()

        # Left Panel Container
        left_panel = QWidget()
        left_panel.setFixedWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        # Create Tab Widget
        tabs = QTabWidget()
        # tabs.setFixedWidth(340) # Removed fixed width from tabs

        # --- Tab 1: Settings ---
        settings_tab = QWidget()
        settings_layout = QVBoxLayout()

        # Controls Group
        controls_group = QGroupBox(tr("Sweep Settings"))
        form = QFormLayout()

        # Sweep Mode removed, Fast Chirp is standard


        # Routing
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

        # Freqs
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
        self.duration_spin.setValue(1.0)
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
        tabs.addTab(settings_tab, tr("Settings"))

        # --- Tab 2: Display ---
        display_tab = QWidget()
        display_layout = QVBoxLayout()

        display_group = QGroupBox(tr("Display Settings"))
        display_form = QFormLayout()

        # Limit Plot Freq (Max)
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

        # Limit Plot Freq (Min)
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
        self.smooth_combo.addItem(tr("Off"), "off")
        self.smooth_combo.addItem(tr("Light"), "light")
        self.smooth_combo.addItem(tr("Medium"), "medium")
        self.smooth_combo.addItem(tr("Heavy"), "heavy")
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
        display_layout.addStretch()
        display_tab.setLayout(display_layout)
        tabs.addTab(display_tab, tr("Display"))

        # --- Tab 3: Calibration ---
        cal_tab = QWidget()
        cal_tab_layout = QVBoxLayout()

        # Latency
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

        # Reference
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
        tabs.addTab(cal_tab, tr("Calibration"))

        # Add tabs to left layout
        left_layout.addWidget(tabs)

        # Buttons
        self.start_btn = QPushButton(tr("Start Sweep"))
        self.start_btn.setCheckable(True)
        self.start_btn.clicked.connect(self.on_start_stop)
        self.start_btn.setFixedHeight(40)
        left_layout.addWidget(self.start_btn)

        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)

        layout.addWidget(left_panel)

        # Plots
        plot_layout = QVBoxLayout()
        self.mag_plot = pg.PlotWidget(title=tr("Magnitude Response"))
        self.mag_plot.setLabel("left", tr("Magnitude"), units="dB")
        self.mag_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.mag_plot.setLogMode(x=True, y=False)
        self.mag_plot.showGrid(x=True, y=True)
        self.mag_curve = self.mag_plot.plot(pen="g")

        # Coherence Axis (Right)
        self.coh_axis = pg.AxisItem("right")
        self.coh_axis.setLabel(tr("Coherence"), units="")
        self.mag_plot.plotItem.layout.addItem(self.coh_axis, 2, 3)

        self.coh_view = pg.ViewBox()
        self.coh_axis.linkToView(self.coh_view)
        self.mag_plot.plotItem.scene().addItem(self.coh_view)
        self.coh_view.setXLink(self.mag_plot.plotItem.vb)
        self.coh_view.setYRange(0, 1.05, padding=0)

        self.coh_view.setLogMode(False, False)
        self.coh_curve = pg.PlotCurveItem(pen="c") # Cyan for visibility
        self.coh_view.addItem(self.coh_curve)

        self.mag_plot.plotItem.vb.sigResized.connect(self.update_coh_views)

        plot_layout.addWidget(self.mag_plot)

        self.phase_plot = pg.PlotWidget(title=tr("Phase Response"))
        self.phase_plot.setLabel("left", tr("Phase"), units="deg")
        self.phase_plot.setLabel("bottom", tr("Frequency"), units="Hz")
        self.phase_plot.setLogMode(x=True, y=False)
        self.phase_plot.showGrid(x=True, y=True)
        self.phase_curve = self.phase_plot.plot(pen="y")

        # Group Delay Axis (Right)
        self.gd_axis = pg.AxisItem("right")
        self.gd_axis.setLabel(tr("Group Delay"), units="s")
        self.phase_plot.plotItem.layout.addItem(self.gd_axis, 2, 3)

        self.gd_view = pg.ViewBox()
        self.gd_axis.linkToView(self.gd_view)
        self.phase_plot.plotItem.scene().addItem(self.gd_view)
        self.gd_view.setXLink(self.phase_plot.plotItem.vb)

        # Disable log mode for the overlay view (we will manually log the data)
        self.gd_view.setLogMode(False, False)

        self.gd_curve = pg.PlotCurveItem(pen="r")
        self.gd_view.addItem(self.gd_curve)

        # 同期処理
        self.phase_plot.plotItem.vb.sigResized.connect(self.update_gd_views)

        plot_layout.addWidget(self.phase_plot)

        layout.addLayout(plot_layout)
        self.setLayout(layout)
        self.on_routing_changed(self.in_combo.currentIndex())



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
        if self.module.input_mode in ["XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"]:
            if "XTALK" in self.module.input_mode:
                self.mag_plot.setTitle(tr("Crosstalk (Meas / Ref)"))
            else:
                self.mag_plot.setTitle(tr("Transfer Function (Meas / Ref)"))
            self.single_mode_combo.setEnabled(False)
            self.unit_combo.setEnabled(False)  # Transfer mode is always relative dB
        else:
            self.mag_plot.setTitle(tr("Magnitude Response"))
            self.single_mode_combo.setEnabled(True)
            self.unit_combo.setEnabled(self.single_mode_combo.currentData() == "absolute")

    def on_display_mode_changed(self, index):
        is_transfer_mode = self.module.input_mode in ["XFER", "XTALK_LR", "XTALK_RL", "XFER_REV"]
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
        print(f"Error: {msg}")
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
        print("Reference trace stored.")

    def on_clear_reference(self):
        self.module.reference_trace = None
        self.refresh_plots()

    def on_apply_reference_changed(self, checked):
        self.refresh_plots()

    def on_start_stop(self, checked):
        if checked:
            self.freqs = []
            self.mags = []
            self.phases = []
            self.cohs = []
            self.mag_curve.setData([], [])
            self.phase_curve.setData([], [])
            self.gd_curve.setData([], [])
            self.coh_curve.setData([], [])
            self.ir_snr_label.setText(tr("IR SNR: -- dB"))
            self.start_btn.setText(tr("Stop Sweep"))
            self.module.start_sweep()
        else:
            self.module.stop_sweep()
            self.start_btn.setText(tr("Start Sweep"))

    def on_sweep_finished(self):
        self.start_btn.setChecked(False)
        self.start_btn.setText(tr("Start Sweep"))

    def update_gd_views(self):
        # Keep the GD view aligned with the main view
        self.gd_view.setGeometry(self.phase_plot.plotItem.vb.sceneBoundingRect())

    def update_coh_views(self):
        self.coh_view.setGeometry(self.mag_plot.plotItem.vb.sceneBoundingRect())

    def on_ir_snr_result(self, snr):
        self.ir_snr_label.setText(tr("IR SNR: {0:.1f} dB").format(snr))

    def update_plot(self, freq, mag, phase, coh):
        self.freqs.append(freq)
        self.mags.append(mag)
        self.phases.append(phase)
        self.cohs.append(coh)
        self.refresh_plots()

    def _apply_smoothing(self, freqs, mags, phases, mode):
        # Apply simple Savitzky-Golay smoothing in the display domain; leave data unchanged when disabled.
        if not len(freqs):
            return mags, phases

        key = (mode or "off").lower()
        window_map = {
            "light": 5,
            "medium": 11,
            "heavy": 21,
        }
        window = window_map.get(key)
        if window is None:
            return mags, phases

        # Window length must be odd and not exceed available points.
        max_len = len(freqs) if len(freqs) % 2 == 1 else len(freqs) - 1
        window = min(window, max_len)
        if window < 3:
            return mags, phases

        mags_smooth = savgol_filter(mags, window_length=window, polyorder=2)

        # Unwrap before smoothing phase to avoid discontinuities, then re-wrap to [-180, 180].
        phase_unwrapped = np.unwrap(np.radians(phases))
        phase_smooth_rad = savgol_filter(phase_unwrapped, window_length=window, polyorder=2)
        phase_smooth = np.degrees(phase_smooth_rad)
        phase_smooth = (phase_smooth + 180) % 360 - 180

        return mags_smooth, phase_smooth

    def refresh_plots(self):
        if not self.freqs:
            return

        smooth_mode = self.smooth_combo.currentData()
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

        is_transfer_mode = self.module.input_mode in ["XFER", "XFER_REV", "XTALK_LR", "XTALK_RL"]
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

        y_values, phases_to_plot = self._apply_smoothing(freqs_to_plot, y_values, phases_to_plot, smooth_mode)

        self.mag_curve.setData(freqs_to_plot, y_values)
        self.phase_curve.setData(freqs_to_plot, phases_to_plot)

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
            self.gd_curve.setData([], [])

        # Coherence
        if self.coh_check.isChecked() and len(freqs_to_plot) > 1 and len(self.cohs) == len(self.freqs):
            self.coh_axis.show()
            cohs_arr = np.array(self.cohs)
            cohs_to_plot = cohs_arr[mask]

            if smooth_mode != "off":
                window_map = {"light": 5, "medium": 11, "heavy": 21}
                window = window_map.get(smooth_mode, 5)
                max_len = len(cohs_to_plot) if len(cohs_to_plot) % 2 == 1 else len(cohs_to_plot) - 1
                window = min(window, max_len)
                if window >= 3:
                    cohs_to_plot = savgol_filter(cohs_to_plot, window_length=window, polyorder=2)
                    cohs_to_plot = np.clip(cohs_to_plot, 0, 1)

            log_freqs = np.log10(freqs_to_plot)
            self.coh_curve.setData(log_freqs, cohs_to_plot)
            self.update_coh_views()
        else:
            self.coh_axis.hide()
            self.coh_curve.setData([], [])
