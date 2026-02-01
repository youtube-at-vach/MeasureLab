import argparse
import numpy as np
import scipy.signal
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
    QFrame,
    QMessageBox,
    QTabWidget,
)


from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.measurement_modules.base import MeasurementModule


# Precomputed Hilbert coefficients for fallback (approx 48kHz, width=800, 65 taps)
_FALLBACK_HILBERT_COEFFS = [
    -0.0000316474, 0.0105268582, 0.0000140129, 0.0064320416, -0.0000026942,
    0.0083717445, -0.0000005448, 0.0107013535, 0.0000004666, 0.0134939067,
    -0.0000005078, 0.0168371142, -0.0000028906, 0.0208555232, -0.0000030355,
    0.0257464826, -0.0000002995, 0.0318132853, 0.0000007285, 0.0395192771,
    -0.0000018136, 0.0496883805, 0.0000014406, 0.063920532, -0.0000002686,
    0.0855646504, 0.0000006833, 0.1234425048, -0.0000003739, 0.2098599827,
    -0.000001463, 0.6358343337, 0.0, -0.6358343337, 0.000001463,
    -0.2098599827, 0.0000003739, -0.1234425048, -0.0000006833, -0.0855646504,
    0.0000002686, -0.063920532, -0.0000014406, -0.0496883805, 0.0000018136,
    -0.0395192771, -0.0000007285, -0.0318132853, 0.0000002995, -0.0257464826,
    0.0000030355, -0.0208555232, 0.0000028906, -0.0168371142, 0.0000005078,
    -0.0134939067, -0.0000004666, -0.0107013535, 0.0000005448, -0.0083717445,
    0.0000026942, -0.0064320416, -0.0000140129, -0.0105268582, 0.0000316474
]


class UltrasoundModulator(MeasurementModule):
    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self.is_running = False
        self.callback_id = None

        # Parameters
        self.carrier_freq = 40000.0
        self.modulation_depth = 1.0  # 0.0 to 1.0
        self.lpf_cutoff = 8000.0
        self.output_gain = 1.0
        self.input_gain = 1.0
        self.enable_predistortion = False
        self.bypass = False
        self.input_mode = "L"  # L, R, Stereo
        self.output_mode = "R"  # L, R, Stereo
        self.modulation_mode = "DSB"  # DSB, USB, LSB

        # Internal State
        self._phase = 0.0
        self._filter_sos = None
        self._filter_zi = None
        self._prev_cutoff = 0.0
        self._prev_fs = 0.0
        self._hilbert_coeffs = None
        self._hilbert_zi = None
        self._delay_zi = None
        self.input_level = 0.0
        self.output_level = 0.0

    @property
    def name(self) -> str:
        return "Ultrasound AM Modulator"

    @property
    def description(self) -> str:
        return "Real-time AM modulator for ultrasonic speakers (40kHz)"

    def run(self, args: argparse.Namespace):
        print("Ultrasound Modulator running from CLI (not fully implemented)")

    def get_widget(self):
        return UltrasoundModulatorWidget(self)

    def _update_filter(self, fs):
        if fs != self._prev_fs or self.lpf_cutoff != self._prev_cutoff:
            if self.lpf_cutoff >= fs / 2:
                # Bypass filter if cutoff is too high
                self._filter_sos = None
                self._filter_zi = None
            else:
                self._filter_sos = scipy.signal.butter(4, self.lpf_cutoff, fs=fs, output="sos")
                self._filter_zi = scipy.signal.sosfilt_zi(self._filter_sos)
                # If we had multiple channels, we would need independent zi for each channel
                # For now, we'll handle stereo by duplicating state if strictly needed,
                # or just filtering channels independently with new zi if it resets.
                # To avoid clicks on param change, we ideally keep state, but zi shape depends on order.
                # Simple approach: reset filter on param change.
                self._filter_zi = np.zeros((self._filter_sos.shape[0], 2))  # Stereo state

            self._prev_fs = fs
            self._prev_cutoff = self.lpf_cutoff

            # Update Hilbert Filter for SSB
            # Design a Hilbert transformer using Remez exchange algorithm
            if self._hilbert_coeffs is None or fs != self._prev_fs:
                # Bandwidth: 800Hz to Nyquist - 800Hz
                # Taps: 65 (Group delay = 32 samples)
                # Note: 100Hz width requires ~500 taps. 800Hz width allows -40dB with 65 taps.
                numtaps = 65
                width = 800.0
                bands = [width, fs / 2 - width]
                try:
                    self._hilbert_coeffs = scipy.signal.remez(numtaps, bands, [1], type="hilbert", fs=fs)
                except Exception as e:
                    print(f"Error designing Hilbert filter: {e}. Fallback to basic.")
                    # Fallback to precomputed coefficients
                    self._hilbert_coeffs = np.array(_FALLBACK_HILBERT_COEFFS)

                # Reset ZI when filter changes
                self._hilbert_zi = None
                self._delay_zi = None

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self._phase = 0.0
        self._filter_sos = None
        self._filter_zi = None
        self._prev_fs = 0.0
        self._hilbert_coeffs = None
        self._hilbert_zi = None
        self._delay_zi = None
        self.input_level = 0.0
        self.output_level = 0.0

        def callback(indata, outdata, frames, time, status):
            if status:
                print(status)

            fs = self.audio_engine.sample_rate

            # 1. Update/Init Filter
            self._update_filter(fs)

            # Prepare Output
            outdata.fill(0)

            if self.bypass:
                # Bypass logic: Pass input through to output (subject to gain)
                # We need to map Input Ch -> Output Ch.

                # Fetch Source(s)
                if self.input_mode == "L":
                    # Mono source from L
                    src = indata[:, 0]  # (frames,)
                elif self.input_mode == "R":
                    # Mono source from R
                    if indata.shape[1] >= 2:
                        src = indata[:, 1]
                    else:
                        src = np.zeros(frames)
                else:  # Stereo
                    if indata.shape[1] >= 2:
                        src = indata[:, :2]  # (frames, 2)
                    else:
                        # Fallback if mono input device in stereo mode?
                        # Just replicate? Or padded? audio_engine usually handles HW mapping.
                        # Assuming logical_in is (frames, 2) usually if stereo requested.
                        # But logical_in depends on engine config.
                        # Let's assume indata has at least 1 channel.
                        if indata.shape[1] == 1:
                            src = np.column_stack((indata[:, 0], indata[:, 0]))
                        else:
                            src = indata[:, :2]

                # Apply input gain (manual normalize/boost)
                src = src * self.input_gain

                # Apply output gain
                src = src * self.output_gain

                # Map to Output
                if self.output_mode == "L":
                    if src.ndim == 1:
                        outdata[:, 0] = src
                    else:  # src is stereo
                        outdata[:, 0] = src[:, 0]  # L -> L
                elif self.output_mode == "R":
                    if src.ndim == 1:
                        if outdata.shape[1] >= 2:
                            outdata[:, 1] = src
                    else:
                        if outdata.shape[1] >= 2:
                            outdata[:, 1] = src[:, 1]  # R -> R
                else:  # Stereo
                    if src.ndim == 1:
                        # Mono source -> L+R
                        outdata[:, 0] = src
                        if outdata.shape[1] >= 2:
                            outdata[:, 1] = src
                    else:
                        # Stereo source -> Stereo Out
                        outdata[:, 0] = src[:, 0]
                        if outdata.shape[1] >= 2:
                            outdata[:, 1] = src[:, 1]
                return

            # 2. Input Processing
            # Determine source signal 'm' (modulation signal)
            # It can be Mono (shape (frames,)) or Stereo (shape (frames, 2)).

            signal_in = None

            if self.input_mode == "L":
                signal_in = indata[:, 0]
            elif self.input_mode == "R":
                if indata.shape[1] >= 2:
                    signal_in = indata[:, 1]
                else:
                    signal_in = np.zeros(frames)
            else:  # Stereo
                # "Both" means L->L, R->R. We act as stereo processor.
                if indata.shape[1] >= 2:
                    signal_in = indata[:, :2]
                elif indata.shape[1] == 1:
                    # Mono input expanded to stereo?
                    signal_in = np.column_stack((indata[:, 0], indata[:, 0]))
                else:
                    signal_in = indata[:, :2]

            # Apply input gain
            signal_in = signal_in * self.input_gain

            # Measure Input Level (Max RMS across channels)
            if signal_in.ndim == 2:  # Stereo
                rms_in = np.sqrt(np.mean(np.mean(signal_in**2, axis=1)))  # Average power of L/R? Or Max?
                # Let's take global RMS
                rms_in = np.sqrt(np.mean(signal_in**2))
            else:
                rms_in = np.sqrt(np.mean(signal_in**2))

            self.input_level = self.input_level * 0.8 + rms_in * 0.2

            # 3. LPF
            m = signal_in
            if self._filter_sos is not None:
                # Handle state dimensions.
                # If m is mono, zi should be (sections, 2).
                # If m is stereo, zi should be (sections, 2, 2).

                channels = 1 if m.ndim == 1 else m.shape[1]

                # Check zi shape
                target_shape = (
                    (self._filter_sos.shape[0], 2) if channels == 1 else (self._filter_sos.shape[0], 2, channels)
                )

                if self._filter_zi is None or self._filter_zi.shape != target_shape:
                    self._filter_zi = np.zeros(target_shape)

                # Execute filter
                # axis=-1 is default.
                # If m is (frames,), axis=-1 is frames. Correct.
                # If m is (frames, 2), axis=-1 is channels. We want to filter along frames (axis 0).

                if channels == 1:
                    m, self._filter_zi = scipy.signal.sosfilt(self._filter_sos, m, zi=self._filter_zi, axis=0)
                else:
                    m, self._filter_zi = scipy.signal.sosfilt(self._filter_sos, m, zi=self._filter_zi, axis=0)

            # 4. Carrier
            # Same carrier for both channels usually.
            t_chunk = np.arange(frames) / fs
            phase = self._phase + 2 * np.pi * self.carrier_freq * t_chunk
            self._phase += 2 * np.pi * self.carrier_freq * (frames / fs)
            self._phase %= 2 * np.pi

            carrier = np.cos(phase)
            # If m is stereo (frames, 2), carrier (frames,) must broadcast.
            # carrier[:, None] -> (frames, 1)
            if m.ndim == 2:
                carrier = carrier[:, np.newaxis]

            # 5. Modulation
            k = self.modulation_depth

            # Prepare modulation signal 'm' for SSB if needed
            if self.modulation_mode == "DSB":
                if self.enable_predistortion:
                    # sqrt(1 + k*m)
                    val = 1.0 + k * m
                    val = np.maximum(val, 0.0)
                    envelope = np.sqrt(val)
                else:
                    envelope = 1.0 + k * m

                modulated = envelope * carrier

            else:  # LSB or USB
                # For SSB, we need Analytic Signal: m_a = m_i + j*m_q
                # m_q is Hilbert Transform of m
                # m_i is m delayed by group delay of Hilbert filter

                if self._hilbert_coeffs is None:
                    # Should have been initialized
                    modulated = np.zeros_like(carrier)
                else:
                    # Hilbert Filtering
                    # Need to handle dimensions carefully.
                    # m: (frames,) or (frames, 2)

                    channels_ssb = 1 if m.ndim == 1 else m.shape[1]
                    # Hilbert coeffs are (taps,).
                    # zi shape: (taps-1, channels)

                    if channels_ssb == 1:
                        target_h_zi_shape = (len(self._hilbert_coeffs) - 1,)
                    else:
                        target_h_zi_shape = (len(self._hilbert_coeffs) - 1, channels_ssb)

                    if self._hilbert_zi is None or self._hilbert_zi.shape != target_h_zi_shape:
                        self._hilbert_zi = np.zeros(target_h_zi_shape)

                    # Filter for Image (Quadrature) component
                    m_q, self._hilbert_zi = scipy.signal.lfilter(
                        self._hilbert_coeffs, 1.0, m, axis=0, zi=self._hilbert_zi
                    )
                    # If mono, m_q is 1D. If stereo, 2D.

                    # Delay for Real (In-phase) component
                    # Group delay is (N-1)/2
                    delay_samples = (len(self._hilbert_coeffs) - 1) // 2

                    # Construct delay filter (impulse at delay_samples)
                    b_delay = np.zeros(delay_samples + 1)
                    b_delay[-1] = 1.0

                    if channels_ssb == 1:
                        target_d_zi_shape = (len(b_delay) - 1,)
                    else:
                        target_d_zi_shape = (len(b_delay) - 1, channels_ssb)

                    if self._delay_zi is None or self._delay_zi.shape != target_d_zi_shape:
                        self._delay_zi = np.zeros(target_d_zi_shape)

                    m_i, self._delay_zi = scipy.signal.lfilter(b_delay, 1.0, m, axis=0, zi=self._delay_zi)

                    # Carrier generation for SSB
                    # We need sin(wt) which is synchronous with cos(wt) used for carrier.
                    # Use the local 'phase' array from Step 4 which is perfectly aligned.
                    sin_carrier = np.sin(phase)
                    if m.ndim == 2:
                        sin_carrier = sin_carrier[:, np.newaxis]

                    # SSB Logic
                    # Standard SSB:
                    # USB: I * cos - Q * sin
                    # LSB: I * cos + Q * sin
                    # Note: Our Hilbert filter implementation seems to produce inverted Q (-sin),
                    # so the signs are flipped relative to standard formula to get correct sideband.

                    term1 = m_i * carrier
                    term2 = m_q * sin_carrier

                    if self.modulation_mode == "USB":
                        sb = term1 + term2
                    else:  # LSB
                        sb = term1 - term2

                    # Carrier re-insertion?
                    # SSB-SC (Suppressed Carrier) or SSB-LC (Large Carrier/AM-compatible)?
                    # Request says "New Carrier Mode... SSB".
                    # Usually for Ultrasound output, we might want the carrier component if it's acting as a parametric array,
                    # but pure SSB is usually SC.
                    # However, for Parametric Audio (audio spotlight), DSB-LC (standard AM) is common.
                    # SSB-LC is often used to reduce bandwidth or distortion.
                    # If we just output SSB-SC, it might not demodulate well in air non-linearity without a strong carrier?
                    # Actually parametric array self-demodulation works on envelopes.
                    # SSB envelope is sqrt(I^2 + Q^2) -> not the audio signal directly?
                    # Wait. E(t)^2 demodulation.
                    # DSB-AM: (1+m)cos -> E = 1+m -> E^2 ~ 1 + 2m + m^2.
                    # SSB: m_i cos - m_q sin. E = sqrt(m_i^2 + m_q^2) = Hilbert Envelope |m|.
                    # This gives |m|^2 upon demodulation. Distorted.
                    # SSB + Carrier (SSB-WC): C cos + m_i cos - m_q sin = (C+m_i)cos - m_q sin.
                    # E = sqrt( (C+m_i)^2 + m_q^2 ) = sqrt( C^2 + 2Cm_i + m_i^2 + m_q^2 ).
                    # Approx C + m_i for C >> m.
                    # So for "SSB Mode" in parametric speakers, we usually mean SSB with Carrier.
                    # Let's add the carrier.

                    # Apply depth k to the sideband part?
                    # AM: (1 + km) cos = cos + k m cos.
                    # SSB equivalent: cos + k * (m_i cos -/+ m_q sin).

                    modulated = carrier + k * sb

            # 6. Gain & Limit
            output_sig = modulated * self.output_gain
            output_sig = np.clip(output_sig, -1.0, 1.0)

            # 7. Route Output
            if self.output_mode == "L":
                # Output to L only
                if output_sig.ndim == 2:
                    # If we processed stereo but want L out?
                    # Usually means "Mix down" or "Take L".
                    # User requirement is vague on "In Stereo -> Out L".
                    # Assuming "Take L".
                    outdata[:, 0] = output_sig[:, 0]
                else:
                    outdata[:, 0] = output_sig
            elif self.output_mode == "R":
                # Output to R only
                if outdata.shape[1] >= 2:
                    if output_sig.ndim == 2:
                        outdata[:, 1] = output_sig[:, 1]
                    else:
                        outdata[:, 1] = output_sig
            else:  # Stereo
                if output_sig.ndim == 2:
                    # Stereo Result -> Stereo Out
                    outdata[:, 0] = output_sig[:, 0]
                    if outdata.shape[1] >= 2:
                        outdata[:, 1] = output_sig[:, 1]
                else:
                    # Mono Result -> Stereo Out (Dual Mono)
                    outdata[:, 0] = output_sig
                    if outdata.shape[1] >= 2:
                        outdata[:, 1] = output_sig

            # Measure Output Level
            if output_sig.ndim == 2:
                rms_out = np.sqrt(np.mean(output_sig**2))
            else:
                rms_out = np.sqrt(np.mean(output_sig**2))
            self.output_level = self.output_level * 0.8 + rms_out * 0.2

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop(self):
        if self.is_running:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_running = False


class UltrasoundModulatorWidget(QWidget):
    def __init__(self, module: UltrasoundModulator):
        super().__init__()
        self.module = module
        self.init_ui()

        # Timer to update status or debug info if needed
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_ui_state)
        self.timer.start(200)

    def init_ui(self):
        layout = QVBoxLayout()

        # Header
        header = QLabel(f"<h3>{tr('Ultrasound AM Modulator')}</h3>")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Safety Status Indicator
        self.safety_frame = QFrame()
        self.safety_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.safety_frame.setLineWidth(2)
        self.safety_frame.setStyleSheet("background-color: #444; border-radius: 5px;")
        safety_layout = QVBoxLayout(self.safety_frame)
        self.safety_label = QLabel(tr("STANDBY"))
        self.safety_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.safety_label.setStyleSheet("font-weight: bold; font-size: 14px; color: white;")
        safety_layout.addWidget(self.safety_label)
        layout.addWidget(self.safety_frame)

        # Tab Widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Modulation Controls
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)

        # Controls Group (Modulation)
        form_layout = QFormLayout()

        # Input Gain
        in_gain_layout = QHBoxLayout()
        self.in_gain_spin = QDoubleSpinBox()
        self.in_gain_spin.setRange(-60.0, 26.0)
        self.in_gain_spin.setSingleStep(0.5)
        self.in_gain_spin.setSuffix(tr(" dB"))
        self.in_gain_spin.setValue(self._lin2db(self.module.input_gain))
        self.in_gain_spin.valueChanged.connect(self.on_in_gain_changed)

        self.in_gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.in_gain_slider.setRange(-600, 260)  # -60.0 to +26.0 dB
        self.in_gain_slider.setValue(int(self._lin2db(self.module.input_gain) * 10))
        self.in_gain_slider.valueChanged.connect(self.on_in_gain_slider_changed)

        in_gain_layout.addWidget(self.in_gain_spin)
        in_gain_layout.addWidget(self.in_gain_slider)
        form_layout.addRow(tr("Input Gain:"), in_gain_layout)

        # Carrier Frequency
        freq_layout = QHBoxLayout()
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(2000.0, 96000.0)
        self.freq_spin.setValue(self.module.carrier_freq)
        self.freq_spin.setSuffix(tr(" Hz"))
        self.freq_spin.valueChanged.connect(self.on_freq_changed)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(0, 1000)
        self.freq_slider.setValue(self._freq_to_slider(self.module.carrier_freq, 2000.0, 96000.0))
        self.freq_slider.valueChanged.connect(self.on_freq_slider_changed)

        freq_layout.addWidget(self.freq_spin)
        freq_layout.addWidget(self.freq_slider)
        form_layout.addRow(tr("Carrier Freq:"), freq_layout)

        # LPF Cutoff
        lpf_layout = QHBoxLayout()
        self.lpf_spin = QDoubleSpinBox()
        self.lpf_spin.setRange(100.0, 20000.0)
        self.lpf_spin.setValue(self.module.lpf_cutoff)
        self.lpf_spin.setSuffix(tr(" Hz"))
        self.lpf_spin.valueChanged.connect(self.on_lpf_changed)

        self.lpf_slider = QSlider(Qt.Orientation.Horizontal)
        self.lpf_slider.setRange(0, 1000)
        self.lpf_slider.setValue(self._freq_to_slider(self.module.lpf_cutoff, 100.0, 20000.0))
        self.lpf_slider.valueChanged.connect(self.on_lpf_slider_changed)

        lpf_layout.addWidget(self.lpf_spin)
        lpf_layout.addWidget(self.lpf_slider)
        form_layout.addRow(tr("Audio LPF:"), lpf_layout)

        # Modulation Depth
        depth_layout = QHBoxLayout()
        self.depth_spin = QDoubleSpinBox()
        self.depth_spin.setRange(0.0, 1.0)
        self.depth_spin.setSingleStep(0.1)
        self.depth_spin.setValue(self.module.modulation_depth)
        self.depth_spin.valueChanged.connect(self.on_depth_changed)

        self.depth_slider = QSlider(Qt.Orientation.Horizontal)
        self.depth_slider.setRange(0, 100)
        self.depth_slider.setValue(int(self.module.modulation_depth * 100))
        self.depth_slider.valueChanged.connect(self.on_depth_slider_changed)

        depth_layout.addWidget(self.depth_spin)
        depth_layout.addWidget(self.depth_slider)
        form_layout.addRow(tr("Mod. Depth (k):"), depth_layout)

        # Output Gain
        gain_layout = QHBoxLayout()
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 6.0)  # Approx 0.001x to 2.0x
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setSuffix(tr(" dB"))
        self.gain_spin.setValue(self._lin2db(self.module.output_gain))
        self.gain_spin.valueChanged.connect(self.on_gain_changed)

        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-600, 60)  # -60.0 to +6.0 dB
        self.gain_slider.setValue(int(self._lin2db(self.module.output_gain) * 10))
        self.gain_slider.valueChanged.connect(self.on_gain_slider_changed)

        gain_layout.addWidget(self.gain_spin)
        gain_layout.addWidget(self.gain_slider)
        form_layout.addRow(tr("Output Gain:"), gain_layout)

        # Mode Selection
        mode_label = QLabel(tr("Carrier Mode:"))
        mode_layout = QHBoxLayout()
        self.mode_bg = QButtonGroup()

        # ID: 0=DSB, 1=USB, 2=LSB
        modes = [(tr("DSB (AM)"), "DSB"), (tr("USB"), "USB"), (tr("LSB"), "LSB")]

        for i, (label, val) in enumerate(modes):
            rb = QRadioButton(label)
            if val == self.module.modulation_mode:
                rb.setChecked(True)
            self.mode_bg.addButton(rb, i)
            mode_layout.addWidget(rb)
        self.mode_bg.idClicked.connect(self.on_mode_rb_id_clicked)
        form_layout.addRow(mode_label, mode_layout)

        tab1_layout.addLayout(form_layout)
        tab1_layout.addStretch()
        self.tabs.addTab(tab1, tr("Modulation"))

        # Tab 2: Settings (Routing & Options)
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)

        # Input/Output Routing
        routing_group = QGroupBox(tr("Routing"))
        routing_layout = QHBoxLayout()

        # Input Group
        in_grp = QGroupBox(tr("Input Channel"))
        in_layout = QHBoxLayout()
        self.in_bg = QButtonGroup()

        # ID: 0=L, 1=R, 2=Stereo
        in_modes = [(tr("L"), "L"), (tr("R"), "R"), (tr("Stereo"), "Stereo")]

        for i, (label, val) in enumerate(in_modes):
            rb = QRadioButton(label)
            if val == self.module.input_mode:
                rb.setChecked(True)
            self.in_bg.addButton(rb, i)
            in_layout.addWidget(rb)
        self.in_bg.idClicked.connect(self.on_in_mode_id_clicked)
        in_grp.setLayout(in_layout)
        routing_layout.addWidget(in_grp)

        # Output Group
        out_grp = QGroupBox(tr("Output Channel"))
        out_layout = QHBoxLayout()
        self.out_bg = QButtonGroup()

        # ID: 0=L, 1=R, 2=Stereo
        out_modes = [(tr("L"), "L"), (tr("R"), "R"), (tr("Stereo"), "Stereo")]

        for i, (label, val) in enumerate(out_modes):
            rb = QRadioButton(label)
            if val == self.module.output_mode:
                rb.setChecked(True)
            self.out_bg.addButton(rb, i)
            out_layout.addWidget(rb)
        self.out_bg.idClicked.connect(self.on_out_mode_id_clicked)
        out_grp.setLayout(out_layout)
        routing_layout.addWidget(out_grp)

        routing_group.setLayout(routing_layout)
        tab2_layout.addWidget(routing_group)

        # Options Group
        opt_group = QGroupBox(tr("Advanced Options"))
        opt_layout = QVBoxLayout()

        self.predist_check = QCheckBox(tr("Enable √ Pre-distortion"))
        self.predist_check.setChecked(self.module.enable_predistortion)
        self.predist_check.toggled.connect(self.on_predist_toggled)
        opt_layout.addWidget(self.predist_check)

        self.bypass_check = QCheckBox(tr("Bypass Modulation (Passthrough)"))
        self.bypass_check.setChecked(self.module.bypass)
        self.bypass_check.toggled.connect(self.on_bypass_toggled)
        opt_layout.addWidget(self.bypass_check)

        opt_group.setLayout(opt_layout)
        tab2_layout.addWidget(opt_group)

        tab2_layout.addStretch()
        self.tabs.addTab(tab2, tr("Settings"))

        # Main Toggle
        self.start_btn = QPushButton(tr("Start Modulation"))
        self.start_btn.setCheckable(True)
        self.start_btn.setStyleSheet("QPushButton:checked { background-color: #ffcccc; }")
        self.start_btn.clicked.connect(self.on_toggle_start)
        layout.addWidget(self.start_btn)

        layout.addStretch()
        self.setLayout(layout)

        # Meters - Add to bottom (outside tabs) but above button?
        meter_group = QGroupBox(tr("Signal Levels"))
        meter_layout = QVBoxLayout()
        in_label = QLabel(tr("Input Level"))
        self.in_bar = QProgressBar()
        self.in_bar.setRange(0, 100)
        self.in_bar.setTextVisible(False)
        self.in_bar.setStyleSheet("QProgressBar::chunk { background-color: #4CAF50; }")
        meter_layout.addWidget(in_label)
        meter_layout.addWidget(self.in_bar)

        out_label = QLabel(tr("Output Level (40kHz)"))
        self.out_bar = QProgressBar()
        self.out_bar.setRange(0, 100)
        self.out_bar.setTextVisible(False)
        self.out_bar.setStyleSheet("QProgressBar::chunk { background-color: #2196F3; }")
        meter_layout.addWidget(out_label)
        meter_layout.addWidget(self.out_bar)

        meter_group.setLayout(meter_layout)

        layout.insertWidget(layout.indexOf(self.start_btn), meter_group)

    def on_in_mode_id_clicked(self, id):
        modes = {0: "L", 1: "R", 2: "Stereo"}
        self.module.input_mode = modes.get(id, "L")

    def on_out_mode_id_clicked(self, id):
        modes = {0: "L", 1: "R", 2: "Stereo"}
        self.module.output_mode = modes.get(id, "R")

    def on_mode_rb_id_clicked(self, id):
        modes = {0: "DSB", 1: "USB", 2: "LSB"}
        self.module.modulation_mode = modes.get(id, "DSB")

    def _lin2db(self, val):
        if val <= 0:
            return -60.0  # Floor
        return 20.0 * np.log10(val)

    def _db2lin(self, val):
        return 10.0 ** (val / 20.0)

    def on_in_gain_changed(self, val):  # val is dB
        self.module.input_gain = self._db2lin(val)
        self.in_gain_slider.blockSignals(True)
        self.in_gain_slider.setValue(int(val * 10))
        self.in_gain_slider.blockSignals(False)

    def on_in_gain_slider_changed(self, val):  # val is int(dB*10)
        gain_db = val / 10.0
        self.module.input_gain = self._db2lin(gain_db)
        self.in_gain_spin.blockSignals(True)
        self.in_gain_spin.setValue(gain_db)
        self.in_gain_spin.blockSignals(False)

    def _freq_to_slider(self, freq, min_f, max_f):
        return int(1000 * (np.log10(freq) - np.log10(min_f)) / (np.log10(max_f) - np.log10(min_f)))

    def _slider_to_freq(self, val, min_f, max_f):
        log_freq = np.log10(min_f) + (val / 1000) * (np.log10(max_f) - np.log10(min_f))
        return 10**log_freq

    def on_freq_changed(self, val):
        self.module.carrier_freq = val
        self.freq_slider.blockSignals(True)
        self.freq_slider.setValue(self._freq_to_slider(val, 2000.0, 96000.0))
        self.freq_slider.blockSignals(False)

    def on_freq_slider_changed(self, val):
        freq = self._slider_to_freq(val, 2000.0, 96000.0)
        self.module.carrier_freq = freq
        self.freq_spin.blockSignals(True)
        self.freq_spin.setValue(freq)
        self.freq_spin.blockSignals(False)

    def on_lpf_changed(self, val):
        self.module.lpf_cutoff = val
        self.lpf_slider.blockSignals(True)
        self.lpf_slider.setValue(self._freq_to_slider(val, 100.0, 20000.0))
        self.lpf_slider.blockSignals(False)

    def on_lpf_slider_changed(self, val):
        freq = self._slider_to_freq(val, 100.0, 20000.0)
        self.module.lpf_cutoff = freq
        self.lpf_spin.blockSignals(True)
        self.lpf_spin.setValue(freq)
        self.lpf_spin.blockSignals(False)

    def on_depth_changed(self, val):
        self.module.modulation_depth = val
        self.depth_slider.blockSignals(True)
        self.depth_slider.setValue(int(val * 100))
        self.depth_slider.blockSignals(False)

    def on_depth_slider_changed(self, val):
        depth = val / 100.0
        self.module.modulation_depth = depth
        self.depth_spin.blockSignals(True)
        self.depth_spin.setValue(depth)
        self.depth_spin.blockSignals(False)

    def on_gain_changed(self, val):  # val is dB
        self.module.output_gain = self._db2lin(val)
        self.gain_slider.blockSignals(True)
        self.gain_slider.setValue(int(val * 10))
        self.gain_slider.blockSignals(False)
        self.update_safety_status()

    def on_gain_slider_changed(self, val):  # val is int(dB*10)
        gain_db = val / 10.0
        self.module.output_gain = self._db2lin(gain_db)
        self.gain_spin.blockSignals(True)
        self.gain_spin.setValue(gain_db)
        self.gain_spin.blockSignals(False)
        self.update_safety_status()

    def update_safety_status(self):
        if not self.module.is_running:
            self.safety_frame.setStyleSheet("background-color: #555; border-radius: 5px; border: 2px solid #777;")
            self.safety_label.setText(tr("STANDBY"))
            self.safety_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #BBB;")
            return

        # Check Output Gain (dB)
        # We need the current dB value.
        # Since we store linear in module, convert back or use spinbox value?
        # Safest is module value.
        gain_lin = self.module.output_gain
        gain_db = self._lin2db(gain_lin)

        if gain_db > 0.0:
            # Dangerous
            self.safety_frame.setStyleSheet("background-color: #FFCDD2; border-radius: 5px; border: 2px solid #F44336;")
            self.safety_label.setText(tr("🔴 DANGEROUS - HIGH INTENSITY 🔴"))
            self.safety_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #B71C1C;")
        elif gain_db > -10.0:
            # Caution
            self.safety_frame.setStyleSheet("background-color: #FFF9C4; border-radius: 5px; border: 2px solid #FBC02D;")
            self.safety_label.setText(tr("🟡 CAUTION - ULTRASOUND ACTIVE 🟡"))
            self.safety_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #F57F17;")
        else:
            # Safe
            self.safety_frame.setStyleSheet("background-color: #C8E6C9; border-radius: 5px; border: 2px solid #4CAF50;")
            self.safety_label.setText(tr("🟢 SAFE - LOW INTENSITY 🟢"))
            self.safety_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #1B5E20;")

    def on_predist_toggled(self, checked):
        self.module.enable_predistortion = checked

    def on_bypass_toggled(self, checked):
        self.module.bypass = checked

    def on_toggle_start(self, checked):
        if checked:
            # Safety Confirmation
            dlg = QMessageBox(self)
            dlg.setWindowTitle(tr("Safety Warning"))
            dlg.setText(
                tr(
                    "High intensity ultrasound can be dangerous to hearing (even if inaudible) and pets.\n\nAre you sure you want to start emission?"
                )
            )
            dlg.setIcon(QMessageBox.Icon.Warning)
            dlg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dlg.setDefaultButton(QMessageBox.StandardButton.No)

            if dlg.exec() != QMessageBox.StandardButton.Yes:
                self.start_btn.setChecked(False)
                return

            self.module.start()
            self.start_btn.setText(tr("Stop Modulation"))
        else:
            self.module.stop()
            self.start_btn.setText(tr("Start Modulation"))

        self.update_safety_status()

    def update_ui_state(self):
        # Update button state if changed externally (though unlikely)
        if self.module.is_running != self.start_btn.isChecked():
            self.start_btn.setChecked(self.module.is_running)
            self.start_btn.setText(tr("Stop Modulation") if self.module.is_running else tr("Start Modulation"))

        # Update Meters
        in_val = int(np.clip(self.module.input_level * 100, 0, 100))
        out_val = int(np.clip(self.module.output_level * 100, 0, 100))

        self.in_bar.setValue(in_val)
        self.out_bar.setValue(out_val)
