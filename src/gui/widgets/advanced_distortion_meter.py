import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.analysis import AudioCalc
from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule
from src.core.fft_manager import fft_manager


class AdvancedDistortionMeter(MeasurementModule):
    # State constants
    STATE_IDLE = 0
    STATE_MEASURING = 1
    STATE_DONE = 2

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.buffer_size = 65536  # High resolution (~0.73 Hz per bin at 48k)

        # Buffers
        self.recording_buffer = np.zeros(self.buffer_size)
        self.output_buffer = np.zeros(self.buffer_size)

        # State
        self.state = self.STATE_IDLE
        self.write_index = 0
        self.read_index = 0

        # Generator Settings
        self.output_enabled = True
        self._gen_amplitude = 0.5
        self.output_channel = 0
        self.input_channel = 0

        # MIM (Multitone) Settings
        self.mim_tone_count = 31
        self.mim_min_freq = 20.0
        self.mim_max_freq = 20000.0
        self._mim_freqs = None

        # PIM Settings
        self.pim_f1 = 1800.0
        self.pim_f2 = 2100.0
        self._pim_f1_actual = None
        self._pim_f2_actual = None
        self.pim_amp_ratio = 1.0  # Equal amplitude

        # Mode
        self.mode = "MIM"  # 'MIM', 'SPDR', 'PIM'

        self.callback_id = None
        self.current_result = None

    @property
    def gen_amplitude(self):
        return self._gen_amplitude

    @gen_amplitude.setter
    def gen_amplitude(self, value):
        if value < 0.0:
            value = 0.0
        elif value > 10.0:
            value = 10.0
        self._gen_amplitude = value
        # Regenerate signal if running
        if self.is_running:
            self._update_output_buffer()

    @property
    def name(self) -> str:
        return "Advanced Distortion Meter"

    @property
    def description(self) -> str:
        return "Advanced distortion measurements including MIM, SPDR, and PIM."

    def run(self, args):
        print("Advanced Distortion Meter running from CLI (not implemented)")

    def get_widget(self):
        return AdvancedDistortionMeterWidget(self)

    def start_analysis(self):
        if self.is_running:
            return

        self.is_running = True
        self.recording_buffer = np.zeros(self.buffer_size)
        self.current_result = None

        # Prepare output signal
        self._update_output_buffer()

        # Reset state
        self.write_index = 0
        self.read_index = 0
        self.state = self.STATE_MEASURING

        def callback(indata, outdata, frames, time, status):
            if status:
                print(status)

            # Output
            if self.output_enabled:
                # Read from cyclic buffer
                # Handle wrapping
                remain = len(self.output_buffer) - self.read_index
                if remain >= frames:
                    self.output_buffer_chunk = self.output_buffer[self.read_index : self.read_index + frames]
                    self.read_index += frames
                else:
                    # Wrap around
                    part1 = self.output_buffer[self.read_index :]
                    part2 = self.output_buffer[: frames - remain]
                    self.output_buffer_chunk = np.concatenate((part1, part2))
                    self.read_index = frames - remain

                # Assign to channels
                sig = self.output_buffer_chunk
                outdata.fill(0)
                if self.output_channel == 0:
                    outdata[:, 0] = sig
                elif self.output_channel == 1:
                    if outdata.shape[1] > 1:
                        outdata[:, 1] = sig
                elif self.output_channel == 2:
                    outdata[:, 0] = sig
                    if outdata.shape[1] > 1:
                        outdata[:, 1] = sig
            else:
                outdata.fill(0)

            # Input (Capture State Machine)
            if self.state == self.STATE_MEASURING:
                capture_ch = self.input_channel
                if indata.shape[1] > capture_ch:
                    new_data = indata[:, capture_ch]
                else:
                    new_data = indata[:, 0]

                # Write to buffer
                space = self.buffer_size - self.write_index
                if space >= frames:
                    self.recording_buffer[self.write_index : self.write_index + frames] = new_data
                    self.write_index += frames
                else:
                    # Fill remainder and stop
                    self.recording_buffer[self.write_index :] = new_data[:space]
                    self.write_index = self.buffer_size
                    self.state = self.STATE_DONE

            # If DONE, we just drop input samples until reset_measurement is called

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_analysis(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False
            self.state = self.STATE_IDLE

    def reset_measurement(self):
        """Called by UI after processing result to start next capture cycle"""
        if not self.is_running:
            return
        self.write_index = 0
        self.state = self.STATE_MEASURING

    def _update_output_buffer(self):
        sr = self.audio_engine.sample_rate
        if self.mode == "MIM":
            self.output_buffer = self._generate_mim(self.buffer_size, sr)
        elif self.mode == "PIM":
            self.output_buffer = self._generate_pim(self.buffer_size, sr)
        elif self.mode == "SPDR":
            self.output_buffer = self._generate_sine(self.buffer_size, sr)
        else:
            self.output_buffer = np.zeros(self.buffer_size)

    def _generate_mim(self, frames, sample_rate):
        # Coherent Multitone Generation
        # 1. Determine Bin Width
        bin_width = sample_rate / frames

        # 2. Setup Base Frequencies
        # Use log spacing
        raw_freqs = np.logspace(np.log10(self.mim_min_freq), np.log10(self.mim_max_freq), self.mim_tone_count)

        # 3. Snap to nearest bins
        self._mim_freqs = np.round(raw_freqs / bin_width) * bin_width

        # 4. Generate Signal
        if self.mim_tone_count == 0 or len(self._mim_freqs) == 0:
            return np.zeros(frames)

        # Random phase optimized for crest factor?
        # Newman phases: phi_n = pi * n^2 / N (quadratic phase) helps Crest Factor.
        # But random is also okay. Let's stick to random but fixed for the buffer.
        phases = np.random.uniform(0, 2 * np.pi, self.mim_tone_count)

        amp_per_tone = self.gen_amplitude / np.sqrt(self.mim_tone_count)

        # Optimize using IFFT
        indices = np.round(self._mim_freqs / bin_width).astype(int)
        spectrum = np.zeros(frames // 2 + 1, dtype=np.complex128)

        # Coefficient: (N/2) * amp * exp(j*(p - pi/2))
        coeffs = (frames / 2) * amp_per_tone * np.exp(1j * (phases - np.pi / 2))

        np.add.at(spectrum, indices, coeffs)

        # Correction for DC (index 0) and Nyquist (index N/2)
        # Unconditionally apply factor 2. If bin is 0, it remains 0.
        spectrum[0] *= 2
        if frames % 2 == 0:
            spectrum[frames // 2] *= 2

        signal = np.fft.irfft(spectrum, n=frames)

        return signal

    def _generate_pim(self, frames, sample_rate):
        # Snap to bins
        bin_width = sample_rate / frames
        f1 = np.round(self.pim_f1 / bin_width) * bin_width
        f2 = np.round(self.pim_f2 / bin_width) * bin_width

        # Store snapped values for calculation
        self._pim_f1_actual = f1
        self._pim_f2_actual = f2

        amp = self.gen_amplitude / 2
        t = np.arange(frames) / sample_rate
        return amp * np.sin(2 * np.pi * f1 * t) + amp * np.sin(2 * np.pi * f2 * t)

    def _generate_sine(self, frames, sample_rate):
        bin_width = sample_rate / frames
        f = np.round(1000.0 / bin_width) * bin_width
        t = np.arange(frames) / sample_rate
        return self.gen_amplitude * np.sin(2 * np.pi * f * t)


class AdvancedDistortionMeterWidget(QWidget):
    def __init__(self, module: AdvancedDistortionMeter):
        super().__init__()
        self.module = module
        self.init_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_analysis)
        self.timer.setInterval(100)  # 10Hz

    def init_ui(self):
        layout = QHBoxLayout()

        # --- Controls ---
        left_panel = QVBoxLayout()
        left_panel.setSpacing(10)

        # Mode
        mode_group = QGroupBox(tr("Measurement Mode"))
        mode_layout = QVBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([tr("MIM (Multitone)"), tr("SPDR"), tr("PIM")])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_group.setLayout(mode_layout)
        left_panel.addWidget(mode_group)

        # Settings Stack
        self.settings_stack = QStackedWidget()

        # 1. MIM Settings
        mim_widget = QWidget()
        mim_layout = QFormLayout()

        self.mim_count_spin = QSpinBox()
        self.mim_count_spin.setRange(3, 100)
        self.mim_count_spin.setValue(self.module.mim_tone_count)
        self.mim_count_spin.valueChanged.connect(lambda v: self.set_param("mim_tone_count", v))
        mim_layout.addRow(tr("Tone Count:"), self.mim_count_spin)

        self.mim_min_spin = QDoubleSpinBox()
        self.mim_min_spin.setRange(10, 20000)
        self.mim_min_spin.setValue(self.module.mim_min_freq)
        self.mim_min_spin.valueChanged.connect(lambda v: self.set_param("mim_min_freq", v))
        mim_layout.addRow(tr("Min Freq:"), self.mim_min_spin)

        self.mim_max_spin = QDoubleSpinBox()
        self.mim_max_spin.setRange(10, 24000)
        self.mim_max_spin.setValue(self.module.mim_max_freq)
        self.mim_max_spin.valueChanged.connect(lambda v: self.set_param("mim_max_freq", v))
        mim_layout.addRow(tr("Max Freq:"), self.mim_max_spin)

        mim_widget.setLayout(mim_layout)
        self.settings_stack.addWidget(mim_widget)

        # 2. SPDR Settings
        spdr_widget = QWidget()
        spdr_layout = QFormLayout()
        spdr_layout.addRow(QLabel(tr("Standard 1kHz Tone")))
        spdr_widget.setLayout(spdr_layout)
        self.settings_stack.addWidget(spdr_widget)

        # 3. PIM Settings
        pim_widget = QWidget()
        pim_layout = QFormLayout()

        self.pim_f1_spin = QDoubleSpinBox()
        self.pim_f1_spin.setRange(10, 20000)
        self.pim_f1_spin.setValue(self.module.pim_f1)
        self.pim_f1_spin.valueChanged.connect(lambda v: self.set_param("pim_f1", v))
        pim_layout.addRow(tr("Freq 1 (Hz):"), self.pim_f1_spin)

        self.pim_f2_spin = QDoubleSpinBox()
        self.pim_f2_spin.setRange(10, 20000)
        self.pim_f2_spin.setValue(self.module.pim_f2)
        self.pim_f2_spin.valueChanged.connect(lambda v: self.set_param("pim_f2", v))
        pim_layout.addRow(tr("Freq 2 (Hz):"), self.pim_f2_spin)

        pim_widget.setLayout(pim_layout)
        self.settings_stack.addWidget(pim_widget)

        left_panel.addWidget(self.settings_stack)

        # Amplitude
        amp_group = QGroupBox(tr("Generator"))
        amp_layout = QFormLayout()
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(-120, 20)
        self.amp_spin.setSingleStep(0.5)
        self.amp_spin.valueChanged.connect(self.on_amp_changed)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["dBFS", "dBV", "dBu", "Vrms"])
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)
        amp_row = QHBoxLayout()
        amp_row.addWidget(self.amp_spin)
        amp_row.addWidget(self.unit_combo)
        amp_layout.addRow(tr("Amplitude:"), amp_row)

        amp_group.setLayout(amp_layout)
        left_panel.addWidget(amp_group)

        # I/O selection
        io_group = QGroupBox(tr("I/O"))
        io_layout = QFormLayout()

        self.in_ch_combo = QComboBox()
        self.in_ch_combo.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)")])
        self.in_ch_combo.currentIndexChanged.connect(lambda i: setattr(self.module, "input_channel", i))
        io_layout.addRow(tr("Input Ch:"), self.in_ch_combo)

        self.out_ch_combo = QComboBox()
        self.out_ch_combo.addItems([tr("Left (Ch 1)"), tr("Right (Ch 2)"), tr("Stereo")])
        self.out_ch_combo.currentIndexChanged.connect(self.on_output_channel_changed)
        io_layout.addRow(tr("Output Ch:"), self.out_ch_combo)

        io_group.setLayout(io_layout)
        left_panel.addWidget(io_group)

        # Control Buttons
        self.start_btn = QPushButton(tr("Start Measurement"))
        self.start_btn.setCheckable(True)
        self.start_btn.clicked.connect(self.on_start_clicked)
        self.start_btn.setStyleSheet("QPushButton:checked { background-color: #ccffcc; }")
        left_panel.addWidget(self.start_btn)

        # Results Display
        self.results_group = QGroupBox(tr("Results"))
        results_layout = QVBoxLayout()

        self.main_metric_label = QLabel("--")
        self.main_metric_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00ff00;")
        self.main_metric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.main_metric_label)

        self.sub_metric_label = QLabel("--")
        self.sub_metric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        results_layout.addWidget(self.sub_metric_label)

        self.results_group.setLayout(results_layout)
        left_panel.addWidget(self.results_group)

        left_panel.addStretch()
        layout.addLayout(left_panel, 1)

        # --- Right Panel: Plots ---
        right_panel = QVBoxLayout()

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel("left", tr("Amplitude"), units="dB")
        self.plot_widget.setLabel("bottom", tr("Frequency"), units="Hz")
        self.plot_widget.setLogMode(x=True, y=False)
        self.plot_widget.setYRange(-140, 0)
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_curve = self.plot_widget.plot(pen="y")

        right_panel.addWidget(self.plot_widget)
        layout.addLayout(right_panel, 3)

        self.setLayout(layout)

        # Initialize amplitude display with current unit
        self.on_unit_changed(self.unit_combo.currentText())
        # Initialize channel selectors
        self.in_ch_combo.setCurrentIndex(self.module.input_channel)
        self.out_ch_combo.setCurrentIndex(self.module.output_channel)

    def set_param(self, name, value):
        setattr(self.module, name, value)
        if self.module.is_running:
            self.module._update_output_buffer()

    def on_mode_changed(self, index):
        if index == 0:  # MIM
            self.module.mode = "MIM"
            self.settings_stack.setCurrentIndex(0)
        elif index == 1:  # SPDR
            self.module.mode = "SPDR"
            self.settings_stack.setCurrentIndex(1)
        elif index == 2:  # PIM
            self.module.mode = "PIM"
            self.settings_stack.setCurrentIndex(2)

        if self.module.is_running:
            self.module._update_output_buffer()

        # Reset results
        self.main_metric_label.setText("--")
        self.sub_metric_label.setText("--")
        self.module.reset_measurement()

    def on_output_channel_changed(self, index):
        self.module.output_channel = index

    def on_unit_changed(self, unit):
        amp_linear = self.module.gen_amplitude
        gain = self.module.audio_engine.calibration.output_gain or 1.0

        self.amp_spin.blockSignals(True)
        if unit == "dBFS":
            val = 20 * np.log10(amp_linear + 1e-12)
        elif unit == "dBV":
            v_peak = amp_linear * gain
            v_rms = v_peak / np.sqrt(2)
            val = 20 * np.log10(v_rms + 1e-12)
        elif unit == "dBu":
            v_peak = amp_linear * gain
            v_rms = v_peak / np.sqrt(2)
            val = 20 * np.log10((v_rms + 1e-12) / 0.7746)
        else:  # Vrms
            v_peak = amp_linear * gain
            val = v_peak / np.sqrt(2)

        self.amp_spin.setValue(val)
        self.amp_spin.blockSignals(False)

    def on_amp_changed(self, val):
        unit = self.unit_combo.currentText()
        gain = self.module.audio_engine.calibration.output_gain or 1.0

        if unit == "dBFS":
            amp_linear = 10 ** (val / 20)
        elif unit == "dBV":
            v_rms = 10 ** (val / 20)
            v_peak = v_rms * np.sqrt(2)
            amp_linear = v_peak / gain
        elif unit == "dBu":
            v_rms = 0.7746 * 10 ** (val / 20)
            v_peak = v_rms * np.sqrt(2)
            amp_linear = v_peak / gain
        else:  # Vrms
            v_peak = val * np.sqrt(2)
            amp_linear = v_peak / gain

        if amp_linear > 1.0:
            amp_linear = 1.0
        elif amp_linear < 0.0:
            amp_linear = 0.0

        self.module.gen_amplitude = amp_linear

    def on_start_clicked(self, checked):
        if checked:
            self.module.start_analysis()
            self.timer.start()
            self.start_btn.setText(tr("Stop Measurement"))
        else:
            self.module.stop_analysis()
            self.timer.stop()
            self.start_btn.setText(tr("Start Measurement"))

    def update_analysis(self):
        if not self.module.is_running:
            return

        # Check if measurement batch is complete
        if self.module.state != self.module.STATE_DONE:
            return

        data = self.module.recording_buffer
        sr = self.module.audio_engine.sample_rate

        # Perform FFT
        # Coherent sampling allows Rectangular window (no windowing) for max resolution.
        # Ensure 'fft_manager' is used.
        fft_res = fft_manager.rfft(data)
        freqs = fft_manager.rfftfreq(len(data), 1 / sr)

        # Magnitude in V (Linear)
        # Normalize: |FFT| * 2 / N
        mag = np.abs(fft_res) * 2 / len(data)
        mag_db = 20 * np.log10(mag + 1e-12)

        # Update Plot
        self.plot_curve.setData(freqs, mag_db)

        # Calculate Metrics
        if self.module.mode == "MIM":
            # Need expected tone freqs (snapped)
            if self.module._mim_freqs is not None:
                res = AudioCalc.calculate_multitone_tdn(mag, freqs, self.module._mim_freqs)
                self.main_metric_label.setText(f"TD+N: {res['tdn_db']:.1f} dB")
                self.sub_metric_label.setText(f"{res['tdn']:.4f} %")

        elif self.module.mode == "SPDR":
            # Assume 1kHz fundamental (snapped check?)
            # Since we didn't store the exact snapped freq on module for SPDR,
            # AudioCalc search will find it near 1000.
            res = AudioCalc.calculate_spdr(mag, freqs, 1000.0)
            self.main_metric_label.setText(f"SPDR: {res['spdr_db']:.1f} dB")
            self.sub_metric_label.setText(
                f"Max Spur: {res['max_spur_freq']:.0f} Hz ({20 * np.log10(res['max_spur_amp'] + 1e-12):.1f} dB)"
            )

        elif self.module.mode == "PIM":
            f1 = self.module._pim_f1_actual if self.module._pim_f1_actual is not None else self.module.pim_f1
            f2 = self.module._pim_f2_actual if self.module._pim_f2_actual is not None else self.module.pim_f2
            res = AudioCalc.calculate_pim(mag, freqs, f1, f2)
            self.main_metric_label.setText(f"PIM: {res['pim_db']:.1f} dBc")
            products_str = ", ".join([f"{p['order']}th" for p in res["products"]])
            self.sub_metric_label.setText(f"Orders: {products_str}")

        # Restart Measurement for next batch
        self.module.reset_measurement()
