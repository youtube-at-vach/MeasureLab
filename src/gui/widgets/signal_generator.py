import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import scipy.signal
except ImportError:
    scipy = None

from src.core.audio_engine import AudioEngine
from src.core.localization import tr
from src.core.fft_manager import WARMUP_SIZES, MEDIUM_SIZES
from src.measurement_modules.base import MeasurementModule


logger = logging.getLogger(__name__)


@dataclass
class SignalParameters:
    waveform: str = "sine"
    frequency: float = 1000.0
    amplitude: float = 0.5
    noise_color: str = "white"

    # FM parameters (frequency modulation)
    fm_enabled: bool = False
    fm_frequency: float = 5.0  # Hz (modulator frequency)
    fm_deviation: float = 100.0  # Hz (peak deviation)

    # ΦM parameters (phase modulation)
    pm_enabled: bool = False
    pm_frequency: float = 5.0  # Hz (modulator frequency)
    pm_deviation_deg: float = 30.0  # degrees (peak phase deviation)

    # AM parameters (amplitude modulation)
    am_enabled: bool = False
    am_frequency: float = 5.0  # Hz (modulator frequency)
    am_depth: float = 50.0  # % (0..100)

    # Sweep parameters
    sweep_enabled: bool = False
    start_freq: float = 20.0
    end_freq: float = 20000.0
    sweep_duration: float = 5.0
    log_sweep: bool = True

    # Filter Parameters (BPF/LPF/HPF)
    lpf_enabled: bool = False
    lpf_freq: float = 20000.0
    lpf_order: int = 4

    hpf_enabled: bool = False
    hpf_freq: float = 20.0
    hpf_order: int = 4

    # Advanced Signal Parameters
    multitone_count: int = 10
    mls_order: int = 15
    burst_on_cycles: int = 10
    burst_off_cycles: int = 90
    burst_windowed: bool = False

    # New Parameters
    pulse_width: float = 50.0  # %
    sawtooth_type: str = "Raising"
    noise_amplitude: float = 0.1
    phase_offset: float = 0.0  # Degrees

    # Inter-channel time alignment (positive = delay this channel)
    delay_ms: float = 0.0  # ms

    # PRBS Parameters
    prbs_order: int = 15
    prbs_seed: int = 1

    # Frequency Snapping
    bin_center_snap: bool = False
    fft_size: int = 16384

    # Frequency Calibration
    use_freq_cal: bool = False

    # Internal state (not shared/copied usually, but kept here for simplicity per channel)
    _phase: float = 0.0
    _sweep_time: float = 0.0
    _buffer: Optional[np.ndarray] = None
    _buffer_index: int = 0

    # FM/phase-accumulator state (radians)
    _carrier_phase_rad: float = 0.0
    _fm_phase_rad: float = 0.0
    _pm_phase_rad: float = 0.0
    _am_phase_rad: float = 0.0

    # Filter state
    _lpf_zi: Optional[np.ndarray] = None
    _hpf_zi: Optional[np.ndarray] = None

    # Filter cache
    _lpf_sos: Optional[np.ndarray] = None
    _lpf_cache_key: Optional[Tuple] = None
    _hpf_sos: Optional[np.ndarray] = None
    _hpf_cache_key: Optional[Tuple] = None


class SignalGenerator(MeasurementModule):
    BUFFERED_WAVEFORMS = ["noise", "multitone", "mls", "burst", "prbs"]

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        self.params_L = SignalParameters()
        self.params_R = SignalParameters()

        # Output Routing: 'L', 'R', 'STEREO'
        self.output_mode = "STEREO"

        self.is_playing = False
        self.callback_id = None

    @property
    def name(self) -> str:
        return "Signal Generator"

    @property
    def description(self) -> str:
        return "Generates advanced test signals (Sine, Square, Noise, Sweeps) with independent channel control"

    def get_widget(self):
        return SignalGeneratorWidget(self)

    def _get_cal_factor(self, params: SignalParameters) -> float:
        if getattr(params, "use_freq_cal", False) and hasattr(self.audio_engine, "calibration"):
            cal = self.audio_engine.calibration
            if hasattr(cal, "get_active_frequency_calibration"):
                val = cal.get_active_frequency_calibration()
                return 1.0 / val if val > 0 else 1.0
            val = getattr(cal, "frequency_calibration", 1.0)
            return 1.0 / val if val > 0 else 1.0
        return 1.0

    def _generate_noise_buffer(self, params: SignalParameters, sample_rate, duration=5.0):
        """Pre-generates a buffer of colored noise."""
        num_samples = int(sample_rate * duration)

        # White noise base
        white = np.random.randn(num_samples)

        if params.noise_color == "white":
            # Normalize
            max_val = np.max(np.abs(white))
            if max_val > 0:
                white /= max_val
            return white

        # FFT filtering
        fft = np.fft.rfft(white)
        # Apply calibration factor to frequencies so that shaping is correctly aligned
        cal_factor = self._get_cal_factor(params)
        freqs = np.fft.rfftfreq(num_samples, d=1 / (sample_rate / cal_factor))

        scaling = np.ones_like(freqs)

        if params.noise_color == "pink":
            # 1/f^0.5 (-3dB/oct)
            scaling[1:] = 1 / np.sqrt(freqs[1:])
            scaling[0] = 0
        elif params.noise_color == "brown":
            # 1/f (-6dB/oct)
            scaling[1:] = 1 / freqs[1:]
            scaling[0] = 0
        elif params.noise_color == "blue":
            # f^0.5 (+3dB/oct)
            scaling = np.sqrt(freqs)
        elif params.noise_color == "violet":
            # f (+6dB/oct)
            scaling = freqs
        elif params.noise_color == "grey":
            # Simplified inverted A-weighting
            f = freqs
            f**2
            c1 = 12194.217**2
            c2 = 20.6**2
            c3 = 107.7**2
            c4 = 737.9**2

            f_safe = f.copy()
            f_safe[0] = 1.0
            f2_safe = f_safe**2

            num = c1 * (f2_safe**2)
            denom = (f2_safe + c2) * np.sqrt((f2_safe + c3) * (f2_safe + c4)) * (f2_safe + c1)
            a_weight = num / denom

            scaling = 1.0 / (a_weight + 1e-12)

            idx_1k = np.argmin(np.abs(freqs - 1000))
            if idx_1k < len(scaling):
                ref_gain = scaling[idx_1k]
                scaling /= ref_gain

            scaling = np.minimum(scaling, 100.0)
            scaling[0] = 0

        fft = fft * scaling
        noise = np.fft.irfft(fft)

        # Normalize
        max_val = np.max(np.abs(noise))
        if max_val > 0:
            noise /= max_val

        return noise

    def _generate_multitone(self, params: SignalParameters, sample_rate):
        """Generates a Crest-Factor optimized Multitone signal."""
        cal_factor = self._get_cal_factor(params)
        
        if params.start_freq >= params.end_freq:
            freqs = np.array([params.start_freq])
        else:
            freqs = np.logspace(np.log10(params.start_freq), np.log10(params.end_freq), params.multitone_count)

        freqs = freqs * cal_factor

        N = int(sample_rate)  # 1 second buffer
        bin_width = sample_rate / N
        freqs = np.round(freqs / bin_width) * bin_width

        # Optimize using IFFT (sum of sines -> Inverse Fourier Transform)
        # 100x-1000x faster than loop for large tone counts
        if len(freqs) == 0:
            return np.zeros(N)

        phases = np.pi * (np.arange(len(freqs)) ** 2) / len(freqs)

        indices = np.round(freqs / bin_width).astype(int)
        spectrum = np.zeros(N // 2 + 1, dtype=np.complex128)

        # sin(wt + p) = cos(wt + p - pi/2)
        # We construct the positive frequency spectrum for irfft.
        # Coefficient for cos(wt + phi) is (N/2) * exp(j * phi)
        coeffs = (N / 2) * np.exp(1j * (phases - np.pi / 2))

        # Accumulate coefficients (handles duplicate bins if any)
        np.add.at(spectrum, indices, coeffs)

        # Correction for DC (index 0) and Nyquist (index N/2)
        # Unconditionally apply factor 2. If bin is 0, it remains 0.
        spectrum[0] *= 2
        if N % 2 == 0:
            spectrum[N // 2] *= 2

        signal = np.fft.irfft(spectrum, n=N)

        max_val = np.max(np.abs(signal))
        if max_val > 0:
            signal /= max_val

        return signal

    def _generate_mls(self, params: SignalParameters, sample_rate):
        """Generates a Maximum Length Sequence (MLS)."""
        taps = {
            10: [10, 3],
            11: [11, 2],
            12: [12, 8, 2, 1],
            13: [13, 5, 2, 1],
            14: [14, 12, 2, 1],
            15: [15, 1],
            16: [16, 12, 3, 1],
            17: [17, 3],
            18: [18, 7],
        }

        order = params.mls_order
        if order not in taps:
            order = 15

        try:
            import scipy.signal

            seq, state = scipy.signal.max_len_seq(order)
            signal = seq.astype(float) * 2 - 1
            return signal
        except Exception:
            logger.warning("scipy.signal.max_len_seq not found/failed, using optimized fallback")

            # Recurrence-based generation: y[i] = y[i-t1] ^ y[i-t2] ...
            # This is significantly faster than bitwise simulation.
            # Taps for MLS are defined such that they satisfy this recurrence.

            N = 2**order - 1
            raw_output = [1] * N  # Initialize with 1s (initial state)

            current_taps = taps[order]

            if len(current_taps) == 2:
                t1, t2 = current_taps
                for i in range(order, N):
                    raw_output[i] = raw_output[i - t1] ^ raw_output[i - t2]
            elif len(current_taps) == 4:
                t1, t2, t3, t4 = current_taps
                for i in range(order, N):
                    raw_output[i] = raw_output[i - t1] ^ raw_output[i - t2] ^ raw_output[i - t3] ^ raw_output[i - t4]
            else:
                # Generic fallback for any number of taps
                for i in range(order, N):
                    val = 0
                    for t in current_taps:
                        val ^= raw_output[i - t]
                    raw_output[i] = val

            signal = np.array(raw_output, dtype=float) * 2 - 1
            return signal

    def _generate_burst(self, params: SignalParameters, sample_rate):
        """Generates a Tone Burst."""
        cal_factor = self._get_cal_factor(params)
        target_freq = params.frequency * cal_factor
        
        total_cycles = params.burst_on_cycles + params.burst_off_cycles
        cycle_duration = 1.0 / target_freq if target_freq > 0 else 1.0
        total_duration = total_cycles * cycle_duration

        num_samples = int(total_duration * sample_rate)
        t = np.arange(num_samples) / sample_rate

        sine = np.sin(2 * np.pi * target_freq * t)

        on_duration = params.burst_on_cycles * cycle_duration
        on_samples = int(on_duration * sample_rate)

        envelope = np.zeros(num_samples)
        on_samples = int(np.clip(on_samples, 0, num_samples))

        if on_samples <= 0:
            return envelope

        if params.burst_windowed and on_samples >= 2:
            # Hann window makes the ON segment start/end at 0 (reduces clicks).
            envelope[:on_samples] = np.hanning(on_samples)
        else:
            envelope[:on_samples] = 1.0

        return sine * envelope

    def _generate_prbs(self, params: SignalParameters, sample_rate):
        """Generates a Pseudo-Random Binary Sequence (PRBS/MLS) with a seed."""
        # PRBS is essentially MLS. We use scipy.signal.max_len_seq
        # The 'seed' controls the initial state.

        order = params.prbs_order
        if order < 2:
            order = 2
        if order > 30:
            order = 30  # Limit for sanity

        try:
            import scipy.signal

            # state must be length 'order'
            # We construct a state from the seed
            if params.prbs_seed == 0:
                # Avoid all-zero state which is invalid for LFSR (unless XNOR, but typically XOR)
                # max_len_seq assumes default state is all 1s if not provided.
                # Let's ensure we have a valid state.
                state = np.ones(order, dtype=np.int8)
            else:
                np.random.seed(params.prbs_seed)
                # Ensure at least one non-zero
                state = np.random.randint(0, 2, size=order, dtype=np.int8)
                if np.sum(state) == 0:
                    state[0] = 1

            seq, _ = scipy.signal.max_len_seq(order, state=state)
            signal = seq.astype(float) * 2 - 1
            return signal

        except ImportError:
            logger.error("scipy not found, cannot generate PRBS efficiently")
            return np.zeros(100)
        except Exception as e:
            logger.error(f"Error generating PRBS: {e}")
            return np.zeros(100)

    def _prepare_buffer(self, params: SignalParameters, sample_rate):
        if params.waveform == "noise":
            params._buffer = self._generate_noise_buffer(params, sample_rate)
        elif params.waveform == "multitone":
            params._buffer = self._generate_multitone(params, sample_rate)
        elif params.waveform == "mls":
            params._buffer = self._generate_mls(params, sample_rate)
        elif params.waveform == "burst":
            params._buffer = self._generate_burst(params, sample_rate)
        elif params.waveform == "prbs":
            params._buffer = self._generate_prbs(params, sample_rate)
        else:
            params._buffer = None
        params._buffer_index = 0

    def _get_filter_sos(self, params: SignalParameters, filter_type: str, sample_rate: float):
        """Calculates SOS coefficients for LPF or HPF."""
        if scipy is None:
            return None

        try:
            # Determine target parameters based on filter type
            if filter_type == "low":
                order = params.lpf_order
                freq = params.lpf_freq
                current_key = (order, freq, sample_rate, "low")

                # Check LPF cache
                if params._lpf_sos is not None and params._lpf_cache_key == current_key:
                    return params._lpf_sos

                # Cache miss
                if freq <= 0 or freq >= sample_rate / 2:
                    params._lpf_sos = None
                    params._lpf_cache_key = None
                    return None

                sos = scipy.signal.butter(order, freq, btype="low", fs=sample_rate, output='sos')
                params._lpf_sos = sos
                params._lpf_cache_key = current_key
                return sos

            elif filter_type == "high":
                order = params.hpf_order
                freq = params.hpf_freq
                current_key = (order, freq, sample_rate, "high")

                # Check HPF cache
                if params._hpf_sos is not None and params._hpf_cache_key == current_key:
                    return params._hpf_sos

                # Cache miss
                if freq <= 0 or freq >= sample_rate / 2:
                    params._hpf_sos = None
                    params._hpf_cache_key = None
                    return None

                sos = scipy.signal.butter(order, freq, btype="high", fs=sample_rate, output='sos')
                params._hpf_sos = sos
                params._hpf_cache_key = current_key
                return sos

            return None

        except Exception:
            # logger.warning(f"Filter calculation failed: {e}")
            return None

    def _generate_wave_from_phase(self, params: SignalParameters, phase_rad: np.ndarray) -> np.ndarray:
        """
        Helper to generate waveform samples from a phase array (in radians).
        Handles sine, square, triangle, sawtooth, pulse, tone_noise.
        """
        offset_rad = np.radians(params.phase_offset)

        if params.waveform == "sine":
            return params.amplitude * np.sin(phase_rad + offset_rad)

        elif params.waveform == "square":
            return params.amplitude * np.sign(np.sin(phase_rad + offset_rad))

        elif params.waveform == "tone_noise":
            signal = params.amplitude * np.sin(phase_rad + offset_rad)
            # Use size of phase_rad for noise generation
            noise = params.noise_amplitude * np.random.uniform(-1, 1, size=phase_rad.size)
            signal += noise
            return signal

        # Cycle-based waveforms
        # cycles = phase / 2pi
        # off_cycles = offset_deg / 360
        cycles = phase_rad / (2.0 * np.pi)
        off_cycles = params.phase_offset / 360.0

        if params.waveform == "triangle":
            return params.amplitude * (2 * np.abs(2 * ((cycles + off_cycles) % 1) - 1) - 1)

        elif params.waveform == "sawtooth":
            raw_saw = 2 * ((cycles + off_cycles) % 1) - 1
            if params.sawtooth_type == "Falling":
                raw_saw *= -1
            return params.amplitude * raw_saw

        elif params.waveform == "pulse":
            duty = params.pulse_width / 100.0
            ramp = (cycles + off_cycles) % 1
            return params.amplitude * np.where(ramp < duty, 1.0, -1.0)

        return np.zeros_like(phase_rad)

    def start_generation(self):
        if self.is_playing:
            return

        self.is_playing = True
        base_sample_rate = self.audio_engine.sample_rate

        # Reset states
        for params in [self.params_L, self.params_R]:
            params._phase = 0
            params._sweep_time = 0
            params._carrier_phase_rad = 0.0
            params._fm_phase_rad = 0.0
            params._pm_phase_rad = 0.0
            params._am_phase_rad = 0.0
            params._lpf_zi = None
            params._hpf_zi = None
            self._prepare_buffer(params, base_sample_rate)

        def _phase_from_instantaneous_frequency(params: SignalParameters, f_inst_hz: np.ndarray, sample_rate: float):
            """Integrate instantaneous frequency to phase (radians) with continuity across blocks."""
            # Prevent negative frequencies from flipping waveforms in unexpected ways.
            # Clamp to >= 0 Hz; users can set deviation to 0 if they want no FM.
            if f_inst_hz.size == 0:
                return np.zeros(0, dtype=float)

            f_safe = np.maximum(f_inst_hz, 0.0)
            dphi = (2.0 * np.pi * f_safe) / sample_rate

            # phase[0] should start at current carrier phase.
            phase0 = float(params._carrier_phase_rad)
            phase = phase0 + np.cumsum(dphi) - dphi[0]

            # Advance phase accumulator for next block.
            params._carrier_phase_rad = float(phase0 + np.sum(dphi))
            # Keep bounded to avoid numerical growth.
            params._carrier_phase_rad = float(np.fmod(params._carrier_phase_rad, 2.0 * np.pi))
            return phase

        def generate_channel_signal(params: SignalParameters, frames, t_global):
            def _am_apply(x: np.ndarray, t_global_eff: np.ndarray, sample_rate_eff: float) -> np.ndarray:
                """Apply simple AM (DSB-LC) envelope: x(t) * (1 + m*sin(2π*f_am*t))."""
                if not (params.am_enabled and params.am_frequency > 0 and params.am_depth != 0):
                    return x

                m = float(np.clip(params.am_depth, 0.0, 100.0)) / 100.0
                if m == 0.0:
                    return x

                am_phase0 = float(params._am_phase_rad)
                am_phase = am_phase0 + 2.0 * np.pi * float(params.am_frequency) * t_global_eff
                params._am_phase_rad = float(
                    np.fmod(
                        am_phase0 + 2.0 * np.pi * float(params.am_frequency) * (frames / sample_rate_eff),
                        2.0 * np.pi,
                    )
                )

                env = 1.0 + m * np.sin(am_phase)
                return x * env

            def _filter_apply(x: np.ndarray, sample_rate_eff: float) -> np.ndarray:
                """Apply LPF/HPF if enabled."""
                if scipy is None:
                    return x

                y = x

                # Apply LPF
                if params.lpf_enabled:
                    sos = self._get_filter_sos(params, "low", sample_rate_eff)
                    if sos is not None:
                        if params._lpf_zi is None or params._lpf_zi.shape != (sos.shape[0], 2):
                             params._lpf_zi = scipy.signal.sosfilt_zi(sos) * 0.0 # Start from 0

                        y, params._lpf_zi = scipy.signal.sosfilt(sos, y, zi=params._lpf_zi)

                # Apply HPF
                if params.hpf_enabled:
                    sos = self._get_filter_sos(params, "high", sample_rate_eff)
                    if sos is not None:
                        if params._hpf_zi is None or params._hpf_zi.shape != (sos.shape[0], 2):
                             params._hpf_zi = scipy.signal.sosfilt_zi(sos) * 0.0

                        y, params._hpf_zi = scipy.signal.sosfilt(sos, y, zi=params._hpf_zi)

                return y

            cal_factor = self._get_cal_factor(params)
            
            # Use effective parameters for clean continuous generation
            sample_rate_eff = base_sample_rate / cal_factor if cal_factor > 0 else base_sample_rate
            t_global_eff = t_global * cal_factor

            signal = np.zeros(frames)

            if params._buffer is not None:
                # For burst, support per-channel fractional delay at readout time.
                # This avoids rebuilding buffers and lets users adjust delay live.
                if params.waveform == "burst" and getattr(params, "delay_ms", 0.0) != 0.0:
                    buf = params._buffer
                    buf_len = len(buf)
                    if buf_len > 0:
                        delay_samples = float(params.delay_ms) * float(sample_rate) / 1000.0
                        # Use remainder + explicit wrapping to avoid rare float edge cases
                        # where floor(idx) can equal buf_len.
                        idx = np.remainder(
                            (float(params._buffer_index) + np.arange(frames, dtype=float) - delay_samples),
                            float(buf_len),
                        )

                        floor_idx = np.floor(idx)
                        i0 = np.mod(floor_idx.astype(np.int64, copy=False), buf_len)
                        frac = (idx - floor_idx).astype(float, copy=False)
                        i1 = (i0 + 1) % buf_len

                        signal = (1.0 - frac) * buf[i0] + frac * buf[i1]
                        params._buffer_index = int((params._buffer_index + frames) % buf_len)
                        return _filter_apply(_am_apply(signal * params.amplitude, t_global_eff, sample_rate_eff), sample_rate_eff)

                # Buffer based generation
                chunk_size = frames
                buf_len = len(params._buffer)
                current_idx = 0

                while current_idx < chunk_size:
                    remaining = chunk_size - current_idx
                    available = buf_len - params._buffer_index

                    to_copy = min(remaining, available)
                    signal[current_idx : current_idx + to_copy] = params._buffer[
                        params._buffer_index : params._buffer_index + to_copy
                    ]

                    params._buffer_index += to_copy
                    current_idx += to_copy

                    if params._buffer_index >= buf_len:
                        params._buffer_index = 0

                return _filter_apply(_am_apply(signal * params.amplitude, t_global_eff, sample_rate_eff), sample_rate_eff)

            if params.sweep_enabled:
                # Sweep generation
                current_times_eff = params._sweep_time + t_global_eff
                current_times_eff = np.mod(current_times_eff, params.sweep_duration)

                # If FM is enabled, integrate instantaneous frequency (sweep + FM).
                # Otherwise, preserve legacy analytic sweep phase.
                if params.fm_enabled and params.fm_frequency > 0 and params.fm_deviation != 0:
                    if params.log_sweep:
                        # f(t) = f0 * exp(k t)
                        k = np.log(params.end_freq / params.start_freq) / params.sweep_duration
                        f_base = (
                            params.start_freq * np.exp(k * current_times_eff)
                            if k != 0
                            else np.full_like(current_times_eff, params.start_freq)
                        )
                    else:
                        # f(t) = f0 + k t
                        k = (params.end_freq - params.start_freq) / params.sweep_duration
                        f_base = params.start_freq + k * current_times_eff

                    # Modulator phase advances continuously across blocks.
                    mod_phase0 = float(params._fm_phase_rad)
                    mod_phase = mod_phase0 + 2.0 * np.pi * params.fm_frequency * t_global_eff
                    params._fm_phase_rad = float(
                        np.fmod(mod_phase0 + 2.0 * np.pi * params.fm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                    )

                    f_inst = f_base + params.fm_deviation * np.sin(mod_phase)
                    phase = _phase_from_instantaneous_frequency(params, f_inst, sample_rate_eff)

                    # Optional ΦM (phase modulation) applied as additional phase term.
                    if params.pm_enabled and params.pm_frequency > 0 and params.pm_deviation_deg != 0:
                        pm_phase0 = float(params._pm_phase_rad)
                        pm_phase = pm_phase0 + 2.0 * np.pi * params.pm_frequency * t_global_eff
                        params._pm_phase_rad = float(
                            np.fmod(pm_phase0 + 2.0 * np.pi * params.pm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                        )
                        beta = float(np.radians(params.pm_deviation_deg))
                        phase = phase + beta * np.sin(pm_phase)

                    offset_rad = np.radians(params.phase_offset)
                    signal = params.amplitude * np.sin(phase + offset_rad)
                    params._sweep_time += frames / sample_rate_eff
                    return _filter_apply(_am_apply(signal, t_global_eff, sample_rate_eff), sample_rate_eff)

                if params.log_sweep:
                    k = np.log(params.end_freq / params.start_freq) / params.sweep_duration
                    if k == 0:
                        phase = 2 * np.pi * params.start_freq * current_times_eff
                    else:
                        phase = 2 * np.pi * params.start_freq * (np.exp(k * current_times_eff) - 1) / k
                else:
                    k = (params.end_freq - params.start_freq) / params.sweep_duration
                    phase = 2 * np.pi * (params.start_freq * current_times_eff + 0.5 * k * current_times_eff**2)

                # Optional ΦM (phase modulation) for analytic sweep phase.
                if params.pm_enabled and params.pm_frequency > 0 and params.pm_deviation_deg != 0:
                    pm_phase0 = float(params._pm_phase_rad)
                    pm_phase = pm_phase0 + 2.0 * np.pi * params.pm_frequency * t_global_eff
                    params._pm_phase_rad = float(
                        np.fmod(pm_phase0 + 2.0 * np.pi * params.pm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                    )
                    beta = float(np.radians(params.pm_deviation_deg))
                    phase = phase + beta * np.sin(pm_phase)

                signal = params.amplitude * np.sin(phase)
                params._sweep_time += frames / sample_rate_eff
                return _filter_apply(_am_apply(signal, t_global_eff, sample_rate_eff), sample_rate_eff)

            # Standard waveforms
            offset_rad = np.radians(params.phase_offset)

            # Optional ΦM (works for periodic waveforms only)
            use_pm = bool(
                params.pm_enabled
                and params.pm_frequency > 0
                and params.pm_deviation_deg != 0
                and params.waveform in ["sine", "square", "triangle", "sawtooth", "pulse", "tone_noise"]
            )

            # Optional FM (works for periodic waveforms only)
            use_fm = bool(
                params.fm_enabled
                and params.fm_frequency > 0
                and params.fm_deviation != 0
                and params.waveform in ["sine", "square", "triangle", "sawtooth", "pulse", "tone_noise"]
            )

            if use_fm:
                # Modulator phase advances continuously across blocks.
                t = t_global_eff
                mod_phase0 = float(params._fm_phase_rad)
                mod_phase = mod_phase0 + 2.0 * np.pi * params.fm_frequency * t
                params._fm_phase_rad = float(
                    np.fmod(mod_phase0 + 2.0 * np.pi * params.fm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                )

                f_inst = params.frequency + params.fm_deviation * np.sin(mod_phase)
                phase = _phase_from_instantaneous_frequency(params, f_inst, sample_rate_eff)

                if use_pm:
                    pm_phase0 = float(params._pm_phase_rad)
                    pm_phase = pm_phase0 + 2.0 * np.pi * params.pm_frequency * t
                    params._pm_phase_rad = float(
                        np.fmod(pm_phase0 + 2.0 * np.pi * params.pm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                    )
                    beta = float(np.radians(params.pm_deviation_deg))
                    phase = phase + beta * np.sin(pm_phase)

                signal = self._generate_wave_from_phase(params, phase)
            else:
                # Legacy fixed-frequency phase calculation
                phase_t = (np.arange(frames) + params._phase) / sample_rate_eff
                params._phase += frames

                # If ΦM is enabled, construct explicit phase and use the phase-based definitions.
                if use_pm:
                    t = t_global_eff
                    pm_phase0 = float(params._pm_phase_rad)
                    pm_phase = pm_phase0 + 2.0 * np.pi * params.pm_frequency * t
                    params._pm_phase_rad = float(
                        np.fmod(pm_phase0 + 2.0 * np.pi * params.pm_frequency * (frames / sample_rate_eff), 2.0 * np.pi)
                    )
                    beta = float(np.radians(params.pm_deviation_deg))
                    phase = 2.0 * np.pi * params.frequency * phase_t + beta * np.sin(pm_phase)

                    signal = self._generate_wave_from_phase(params, phase)

                    return _filter_apply(_am_apply(signal, t_global_eff, sample_rate_eff), sample_rate_eff)

                phase_rad = 2.0 * np.pi * params.frequency * phase_t
                signal = self._generate_wave_from_phase(params, phase_rad)

            return _filter_apply(_am_apply(signal, t_global_eff, sample_rate_eff), sample_rate_eff)

        def callback(indata, outdata, frames, time, status):
            if status:
                logger.debug(status)

            t = np.arange(frames) / base_sample_rate
            outdata.fill(0)

            # Left Channel
            if self.output_mode in ["L", "STEREO"]:
                sig_l = generate_channel_signal(self.params_L, frames, t)
                if outdata.shape[1] >= 1:
                    outdata[:, 0] = sig_l

            # Right Channel
            if self.output_mode in ["R", "STEREO"]:
                # If we are in STEREO but want to output the SAME signal if linked?
                # The user requirement says "L and R separate signals".
                # So we always use params_R for Right channel.
                # If the user wants them same, they copy settings in UI.
                sig_r = generate_channel_signal(self.params_R, frames, t)
                if outdata.shape[1] >= 2:
                    outdata[:, 1] = sig_r

        self.callback_id = self.audio_engine.register_callback(callback)

    def stop_generation(self):
        if self.is_playing:
            if self.callback_id is not None:
                self.audio_engine.unregister_callback(self.callback_id)
                self.callback_id = None
            self.is_playing = False

    def update_waveform(self, params: SignalParameters, waveform: str, sample_rate: float):
        """Updates the waveform type and regenerates/clears buffer if needed."""
        params.waveform = waveform

        # Check if new waveform uses buffer
        if waveform in self.BUFFERED_WAVEFORMS:
            self._prepare_buffer(params, sample_rate)
        else:
            # Clear buffer so that standard generation logic is used
            params._buffer = None
            params._buffer_index = 0

    def update_param(self, params: SignalParameters, name: str, value: Any):
        """Updates a parameter and triggers buffer regeneration if necessary."""
        # Check if value actually changed
        current_value = getattr(params, name)
        if current_value == value:
            return

        setattr(params, name, value)

        # Buffer regeneration logic
        # Only if the waveform is currently active and buffered
        if params.waveform in self.BUFFERED_WAVEFORMS:
            # Check if the changed parameter affects buffer generation for this waveform
            needs_update = False

            if params.waveform == "noise" and name == "noise_color":
                needs_update = True
            elif params.waveform == "multitone" and name in ["multitone_count", "start_freq", "end_freq", "use_freq_cal"]:
                needs_update = True
            elif params.waveform == "mls" and name == "mls_order":
                needs_update = True
            elif params.waveform == "burst" and name in ["frequency", "burst_on_cycles", "burst_off_cycles", "burst_windowed", "use_freq_cal"]:
                needs_update = True
            elif params.waveform == "prbs" and name in ["prbs_order", "prbs_seed"]:
                needs_update = True

            if needs_update:
                sample_rate = self.audio_engine.sample_rate
                self._prepare_buffer(params, sample_rate)


class SignalGeneratorWidget(QWidget):
    def __init__(self, module: SignalGenerator):
        super().__init__()
        self.module = module
        self.current_target = "L"  # 'L', 'R', 'LINK'
        self.init_ui()

    def _set_wave_combo_key(self, key: str):
        for i in range(self.wave_combo.count()):
            if self.wave_combo.itemData(i) == key:
                self.wave_combo.setCurrentIndex(i)
                return

    def _set_fft_size_combo(self, size: int):
        idx = self.fft_size_combo.findData(size)
        if idx >= 0:
            self.fft_size_combo.setCurrentIndex(idx)
        else:
            self.fft_size_combo.setCurrentText(str(size))

    def _apply_waveform_key(self, key: str, *, update_params: bool):
        # Map UI selection to internal params
        if update_params:
            sample_rate = self.module.audio_engine.sample_rate
            target_waveform = key

            if key == "burst_windowed":
                target_waveform = "burst"

            for params in self.get_active_params_list():
                # Set auxiliary flags first because update_waveform/prepare_buffer might use them
                if key == "burst_windowed":
                    params.burst_windowed = True
                elif key == "burst":
                    params.burst_windowed = False

                self.module.update_waveform(params, target_waveform, sample_rate)

        # Dynamic widgets
        self.noise_widget.hide()
        self.multitone_widget.hide()
        self.mls_widget.hide()
        self.mls_widget.hide()
        self.burst_widget.hide()
        self.pulse_widget.hide()
        self.tn_widget.hide()
        self.tn_widget.hide()
        self.sawtooth_widget.hide()
        self.prbs_widget.hide()

        if key == "noise":
            self.noise_widget.show()
        elif key == "multitone":
            self.multitone_widget.show()
        elif key == "mls":
            self.mls_widget.show()
        elif key in ["burst", "burst_windowed"]:
            self.burst_widget.show()
        elif key == "pulse":
            self.pulse_widget.show()
        elif key == "tone_noise":
            self.tn_widget.show()
        elif key == "sawtooth":
            self.sawtooth_widget.show()
        elif key == "prbs":
            self.prbs_widget.show()

        use_freq = key not in ["noise", "mls", "prbs"]
        self.freq_spin.setEnabled(use_freq)
        self.freq_slider.setEnabled(use_freq)

        # Delay UI is only relevant for burst variants (engine applies delay for burst only).
        show_delay = key in ["burst", "burst_windowed"]
        self.delay_label.setVisible(show_delay)
        self.delay_spin.setVisible(show_delay)
        self.delay_slider.setVisible(show_delay)

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Top Control Bar ---
        layout.addLayout(self._create_top_control_bar())

        # --- Target Selector ---
        layout.addLayout(self._create_target_selector())

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # --- Main Controls ---
        layout.addWidget(self._create_signal_params_group())

        # --- Options Tabs ---
        layout.addWidget(self._create_options_tabs())

        layout.addStretch()
        self.setLayout(layout)

        # Initialize UI with current target (L)
        self.load_params_to_ui(self.module.params_L)

    def _create_top_control_bar(self):
        top_bar = QHBoxLayout()

        # Start/Stop
        self.toggle_btn = QPushButton(tr("Start Output"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setMinimumHeight(40)
        self.toggle_btn.clicked.connect(self.on_toggle)
        self.toggle_btn.setStyleSheet("QPushButton:checked { background-color: #ffcccc; font-weight: bold; }")
        top_bar.addWidget(self.toggle_btn, 2)

        # Output Routing (destination is now controlled globally from the status bar)
        routing_group = QGroupBox(tr("Output Routing"))
        routing_layout = QHBoxLayout()
        self.route_l = QRadioButton(tr("Left Only"))
        self.route_r = QRadioButton(tr("Right Only"))
        self.route_stereo = QRadioButton(tr("Stereo (L+R)"))
        self.route_stereo.setChecked(True)

        self.route_group = QButtonGroup()
        self.route_group.addButton(self.route_l)
        self.route_group.addButton(self.route_r)
        self.route_group.addButton(self.route_stereo)

        self.route_group.buttonClicked.connect(self.on_route_changed)

        routing_layout.addWidget(self.route_l)
        routing_layout.addWidget(self.route_r)
        routing_layout.addWidget(self.route_stereo)
        routing_group.setLayout(routing_layout)
        top_bar.addWidget(routing_group, 3)

        return top_bar

    def _create_target_selector(self):
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel(f"<b>{tr('Edit Settings For:')}</b>"))

        self.target_l = QRadioButton(tr("Left Channel"))
        self.target_r = QRadioButton(tr("Right Channel"))
        self.target_link = QRadioButton(tr("Linked (Both)"))
        self.target_l.setChecked(True)

        self.target_group = QButtonGroup()
        self.target_group.addButton(self.target_l)
        self.target_group.addButton(self.target_r)
        self.target_group.addButton(self.target_link)
        self.target_group.buttonClicked.connect(self.on_target_changed)

        target_layout.addWidget(self.target_l)
        target_layout.addWidget(self.target_r)
        target_layout.addWidget(self.target_link)
        target_layout.addStretch()

        return target_layout

    def _create_signal_params_group(self):
        basic_group = QGroupBox(tr("Signal Parameters"))
        basic_layout = QFormLayout()

        self._init_waveform_selector(basic_layout)
        self._init_param_stack(basic_layout)
        self._init_frequency_controls(basic_layout)
        self._init_phase_controls(basic_layout)
        self._init_delay_controls(basic_layout)
        self._init_amplitude_controls(basic_layout)
        self._init_bin_snap_controls(basic_layout)

        basic_group.setLayout(basic_layout)
        return basic_group

    def _init_waveform_selector(self, layout):
        self.wave_combo = QComboBox()
        waveform_items = [
            ("sine", "sine"),
            ("square", "square"),
            ("triangle", "triangle"),
            ("sawtooth", "sawtooth"),
            ("pulse", "pulse"),
            ("tone_noise", "tone_noise"),
            ("noise", "noise"),
            ("multitone", "multitone"),
            ("mls", "mls"),
            ("burst", "burst"),
            ("burst (windowed)", "burst_windowed"),
            ("prbs", "prbs"),
        ]
        for label, key in waveform_items:
            self.wave_combo.addItem(label, key)
        self.wave_combo.currentIndexChanged.connect(self.on_wave_changed)
        layout.addRow(tr("Waveform:"), self.wave_combo)

    def _init_param_stack(self, layout):
        self.param_stack = QWidget()
        self.param_layout = QVBoxLayout(self.param_stack)
        self.param_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Noise Params
        self.noise_widget = QWidget()
        noise_form = QFormLayout(self.noise_widget)
        self.noise_combo = QComboBox()
        self.noise_combo.addItems(["white", "pink", "brown", "blue", "violet", "grey"])
        self.noise_combo.currentTextChanged.connect(lambda v: self.update_param("noise_color", v))
        noise_form.addRow(tr("Color:"), self.noise_combo)

        # 2. Multitone Params
        self.multitone_widget = QWidget()
        mt_form = QFormLayout(self.multitone_widget)
        self.mt_count_spin = QDoubleSpinBox()
        self.mt_count_spin.setDecimals(0)
        self.mt_count_spin.setRange(2, 1000)
        self.mt_count_spin.setValue(10)
        self.mt_count_spin.valueChanged.connect(lambda v: self.update_param("multitone_count", int(v)))
        mt_form.addRow(tr("Tone Count:"), self.mt_count_spin)

        # 3. MLS Params
        self.mls_widget = QWidget()
        mls_form = QFormLayout(self.mls_widget)
        self.mls_order_combo = QComboBox()
        self.mls_order_combo.addItems([str(i) for i in range(10, 19)])
        self.mls_order_combo.setCurrentText("15")
        self.mls_order_combo.currentTextChanged.connect(lambda v: self.update_param("mls_order", int(v)))
        mls_form.addRow(tr("Order (N):"), self.mls_order_combo)

        # 4. Burst Params
        self.burst_widget = QWidget()
        burst_form = QFormLayout(self.burst_widget)
        self.burst_on_spin = QDoubleSpinBox()
        self.burst_on_spin.setDecimals(0)
        self.burst_on_spin.setRange(1, 1000)
        self.burst_on_spin.setValue(10)
        self.burst_on_spin.valueChanged.connect(lambda v: self.update_param("burst_on_cycles", int(v)))
        burst_form.addRow(tr("On Cycles:"), self.burst_on_spin)
        self.burst_off_spin = QDoubleSpinBox()
        self.burst_off_spin.setDecimals(0)
        self.burst_off_spin.setRange(1, 10000)
        self.burst_off_spin.setValue(90)
        self.burst_off_spin.valueChanged.connect(lambda v: self.update_param("burst_off_cycles", int(v)))
        burst_form.addRow(tr("Off Cycles:"), self.burst_off_spin)

        # 5. Pulse Params
        self.pulse_widget = QWidget()
        pulse_form = QFormLayout(self.pulse_widget)
        self.pulse_width_spin = QDoubleSpinBox()
        self.pulse_width_spin.setRange(0.1, 99.9)
        self.pulse_width_spin.setValue(50.0)
        self.pulse_width_spin.setSuffix("%")
        self.pulse_width_spin.valueChanged.connect(lambda v: self.update_param("pulse_width", v))
        pulse_form.addRow(tr("Pulse Width:"), self.pulse_width_spin)

        # 6. Tone+Noise Params
        self.tn_widget = QWidget()
        tn_form = QFormLayout(self.tn_widget)
        self.noise_amp_spin = QDoubleSpinBox()
        self.noise_amp_spin.setRange(0.0, 1.0)
        self.noise_amp_spin.setSingleStep(0.01)
        self.noise_amp_spin.setValue(0.1)
        self.noise_amp_spin.valueChanged.connect(lambda v: self.update_param("noise_amplitude", v))
        tn_form.addRow(tr("Noise Amplitude:"), self.noise_amp_spin)

        # 7. Sawtooth Params
        self.sawtooth_widget = QWidget()
        saw_form = QFormLayout(self.sawtooth_widget)
        self.saw_type_combo = QComboBox()
        self.saw_type_combo.addItems(["Raising", "Falling"])
        self.saw_type_combo.currentTextChanged.connect(lambda v: self.update_param("sawtooth_type", v))
        saw_form.addRow(tr("Type:"), self.saw_type_combo)

        # 8. PRBS Params
        self.prbs_widget = QWidget()
        prbs_form = QFormLayout(self.prbs_widget)

        self.prbs_order_combo = QComboBox()
        # Common PRBS orders: 7, 9, 11, 15, 20, 23, 31 (31 might be too large for buffer? 2GB buffer.. let's limit to 20 ~1M samples)
        self.prbs_order_combo.addItems([str(i) for i in [7, 9, 10, 11, 15, 17, 20, 23]])
        self.prbs_order_combo.setCurrentText("15")
        self.prbs_order_combo.currentTextChanged.connect(lambda v: self.update_param("prbs_order", int(v)))
        prbs_form.addRow(tr("Order (N):"), self.prbs_order_combo)

        self.prbs_seed_spin = (
            QDoubleSpinBox()
        )  # Using DoubleSpinBox for int as it's often more flexible or just use SpinBox
        # Actually QSpinBox is better for ints
        from PyQt6.QtWidgets import QSpinBox

        self.prbs_seed_spin = QSpinBox()
        self.prbs_seed_spin.setRange(0, 999999)
        self.prbs_seed_spin.setValue(1)
        self.prbs_seed_spin.valueChanged.connect(lambda v: self.update_param("prbs_seed", v))
        prbs_form.addRow(tr("Seed:"), self.prbs_seed_spin)

        self.param_layout.addWidget(self.noise_widget)
        self.param_layout.addWidget(self.multitone_widget)
        self.param_layout.addWidget(self.mls_widget)
        self.param_layout.addWidget(self.burst_widget)
        self.param_layout.addWidget(self.pulse_widget)
        self.param_layout.addWidget(self.tn_widget)
        self.param_layout.addWidget(self.sawtooth_widget)
        self.param_layout.addWidget(self.prbs_widget)
        self.noise_widget.hide()
        self.multitone_widget.hide()
        self.mls_widget.hide()
        self.burst_widget.hide()
        self.pulse_widget.hide()
        self.tn_widget.hide()
        self.sawtooth_widget.hide()
        self.prbs_widget.hide()

        layout.addRow(self.param_stack)

    def _init_frequency_controls(self, layout):
        freq_layout = QHBoxLayout()
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(20, 20000)
        self.freq_spin.setValue(1000)
        self.freq_spin.valueChanged.connect(self.on_freq_spin_changed)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(0, 1000)
        self.freq_slider.valueChanged.connect(self.on_freq_slider_changed)

        freq_layout.addWidget(self.freq_spin)
        freq_layout.addWidget(self.freq_slider)
        layout.addRow(tr("Frequency (Hz):"), freq_layout)

    def _init_phase_controls(self, layout):
        phase_layout = QHBoxLayout()
        self.phase_spin = QDoubleSpinBox()
        self.phase_spin.setRange(-180, 180)
        self.phase_spin.setValue(0)
        self.phase_spin.setSuffix(" deg")
        self.phase_spin.valueChanged.connect(self.on_phase_spin_changed)

        self.phase_slider = QSlider(Qt.Orientation.Horizontal)
        self.phase_slider.setRange(-180, 180)
        self.phase_slider.setValue(0)
        self.phase_slider.valueChanged.connect(self.on_phase_slider_changed)

        phase_layout.addWidget(self.phase_spin)
        phase_layout.addWidget(self.phase_slider)
        layout.addRow(tr("Phase Offset:"), phase_layout)

    def _init_delay_controls(self, layout):
        self.delay_label = QLabel(tr("Delay (ms):"))
        delay_layout = QHBoxLayout()
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(-2.0, 2.0)
        self.delay_spin.setDecimals(3)
        self.delay_spin.setSingleStep(0.01)
        self.delay_spin.setValue(0.0)
        self.delay_spin.setSuffix(" ms")
        self.delay_spin.valueChanged.connect(self.on_delay_spin_changed)

        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        # microseconds in slider units for fine control
        self.delay_slider.setRange(-2000, 2000)
        self.delay_slider.setValue(0)
        self.delay_slider.valueChanged.connect(self.on_delay_slider_changed)

        delay_layout.addWidget(self.delay_spin)
        delay_layout.addWidget(self.delay_slider)
        layout.addRow(self.delay_label, delay_layout)

    def _init_amplitude_controls(self, layout):
        amp_layout = QHBoxLayout()
        self.amp_spin = QDoubleSpinBox()
        self.amp_spin.setRange(0, 1.0)
        self.amp_spin.setSingleStep(0.1)
        self.amp_spin.valueChanged.connect(self.on_amp_spin_changed)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Linear (0-1)", "dBFS", "dBV", "dBu", "Vrms", "Vpeak"])
        self.unit_combo.currentTextChanged.connect(self.on_unit_changed)

        self.amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.amp_slider.setRange(0, 100)
        self.amp_slider.valueChanged.connect(self.on_amp_slider_changed)

        amp_layout.addWidget(self.amp_spin)
        amp_layout.addWidget(self.unit_combo)
        amp_layout.addWidget(self.amp_slider)
        layout.addRow(tr("Amplitude:"), amp_layout)

    def _init_bin_snap_controls(self, layout):
        snap_layout = QHBoxLayout()
        self.snap_check = QCheckBox(tr("Snap to Bin Center"))
        self.snap_check.toggled.connect(self.on_snap_toggled)

        self.fft_size_combo = QComboBox()
        self.fft_size_combo.setEditable(True)
        # Add common FFT sizes
        sizes = sorted(list(set(WARMUP_SIZES + MEDIUM_SIZES)))
        for size in sizes:
            self.fft_size_combo.addItem(str(size), size)

        # Set default to 16384 if available, else something reasonable
        idx = self.fft_size_combo.findData(16384)
        if idx >= 0:
            self.fft_size_combo.setCurrentIndex(idx)
        else:
            self.fft_size_combo.setCurrentText("16384")

        self.fft_size_combo.currentTextChanged.connect(self.on_fft_size_changed)

        # Validator for custom input
        from PyQt6.QtGui import QIntValidator
        self.fft_size_combo.setValidator(QIntValidator(2, 10000000))

        # Initial state: disabled unless checked (handled in logic or load_params)
        self.fft_size_combo.setEnabled(False) 

        snap_layout.addWidget(self.snap_check)
        snap_layout.addWidget(QLabel(tr("Window Width:")))
        snap_layout.addWidget(self.fft_size_combo, 1) # Stretch

        # We assume the user wants this associated with "Frequency Snap" label or similar?
        # Or just "Bin Snap"
        layout.addRow(tr("Bin Snap:"), snap_layout)

        # Apply Frequency Calibration Checkbox
        cal_layout = QHBoxLayout()
        self.cal_check = QCheckBox(tr("Apply Frequency Calibration"))
        self.cal_check.toggled.connect(lambda v: self.update_param("use_freq_cal", v))
        cal_layout.addWidget(self.cal_check)
        layout.addRow(tr("Frequency Calibration:"), cal_layout)

    def _create_options_tabs(self):
        tabs = QTabWidget()
        tabs.addTab(self._create_sweep_tab(), tr("Sweep"))
        tabs.addTab(self._create_am_tab(), tr("AM"))
        tabs.addTab(self._create_fm_tab(), tr("FM"))
        tabs.addTab(self._create_pm_tab(), tr("ΦM"))
        tabs.addTab(self._create_lpf_tab(), tr("LPF"))
        tabs.addTab(self._create_hpf_tab(), tr("HPF"))
        return tabs

    def _create_lpf_tab(self):
        filter_widget = QWidget()
        layout = QVBoxLayout(filter_widget)

        # LPF Group
        lpf_group = QGroupBox(tr("Low Pass Filter (LPF)"))
        lpf_group.setCheckable(True)
        lpf_group.setChecked(False)
        lpf_group.toggled.connect(lambda v: self.update_param("lpf_enabled", v))
        self.lpf_group = lpf_group

        lpf_layout = QFormLayout()
        self.lpf_freq_spin = QDoubleSpinBox()
        self.lpf_freq_spin.setRange(20, 20000)
        self.lpf_freq_spin.setValue(20000)
        self.lpf_freq_spin.setGroupSeparatorShown(True)
        self.lpf_freq_spin.valueChanged.connect(lambda v: self.update_param("lpf_freq", v))
        lpf_layout.addRow(tr("Cutoff Freq (Hz):"), self.lpf_freq_spin)

        self.lpf_order_spin = QSpinBox()
        self.lpf_order_spin.setRange(1, 20)
        self.lpf_order_spin.setValue(4)
        self.lpf_order_spin.valueChanged.connect(lambda v: self.update_param("lpf_order", v))
        lpf_layout.addRow(tr("Order:"), self.lpf_order_spin)

        lpf_group.setLayout(lpf_layout)

        layout.addWidget(lpf_group)
        layout.addStretch()

        return filter_widget

    def _create_hpf_tab(self):
        filter_widget = QWidget()
        layout = QVBoxLayout(filter_widget)

        # HPF Group
        hpf_group = QGroupBox(tr("High Pass Filter (HPF)"))
        hpf_group.setCheckable(True)
        hpf_group.setChecked(False)
        hpf_group.toggled.connect(lambda v: self.update_param("hpf_enabled", v))
        self.hpf_group = hpf_group

        hpf_layout = QFormLayout()
        self.hpf_freq_spin = QDoubleSpinBox()
        self.hpf_freq_spin.setRange(20, 20000)
        self.hpf_freq_spin.setValue(20)
        self.hpf_freq_spin.setGroupSeparatorShown(True)
        self.hpf_freq_spin.valueChanged.connect(lambda v: self.update_param("hpf_freq", v))
        hpf_layout.addRow(tr("Cutoff Freq (Hz):"), self.hpf_freq_spin)

        self.hpf_order_spin = QSpinBox()
        self.hpf_order_spin.setRange(1, 20)
        self.hpf_order_spin.setValue(4)
        self.hpf_order_spin.valueChanged.connect(lambda v: self.update_param("hpf_order", v))
        hpf_layout.addRow(tr("Order:"), self.hpf_order_spin)

        hpf_group.setLayout(hpf_layout)

        layout.addWidget(hpf_group)
        layout.addStretch()

        return filter_widget

    def _create_sweep_tab(self):
        sweep_group = QGroupBox(tr("Frequency Sweep (Sine Only)"))
        sweep_group.setCheckable(True)
        sweep_group.setChecked(False)
        sweep_group.toggled.connect(lambda v: self.update_param("sweep_enabled", v))
        self.sweep_group = sweep_group

        sweep_layout = QFormLayout()

        self.start_freq_spin = QDoubleSpinBox()
        self.start_freq_spin.setRange(20, 20000)
        self.start_freq_spin.valueChanged.connect(lambda v: self.update_param("start_freq", v))
        sweep_layout.addRow(tr("Start Freq:"), self.start_freq_spin)

        self.end_freq_spin = QDoubleSpinBox()
        self.end_freq_spin.setRange(20, 20000)
        self.end_freq_spin.valueChanged.connect(lambda v: self.update_param("end_freq", v))
        sweep_layout.addRow(tr("End Freq:"), self.end_freq_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.1, 60.0)
        self.duration_spin.valueChanged.connect(lambda v: self.update_param("sweep_duration", v))
        sweep_layout.addRow(tr("Duration (s):"), self.duration_spin)

        self.log_check = QCheckBox(tr("Logarithmic Sweep"))
        self.log_check.toggled.connect(lambda v: self.update_param("log_sweep", v))
        sweep_layout.addRow(self.log_check)

        sweep_group.setLayout(sweep_layout)
        return sweep_group

    def _create_am_tab(self):
        am_group = QGroupBox(tr("AM (Amplitude Modulation)"))
        am_group.setCheckable(True)
        am_group.setChecked(False)
        am_group.toggled.connect(lambda v: self.update_param("am_enabled", v))
        self.am_group = am_group

        am_layout = QFormLayout()

        self.am_freq_spin = QDoubleSpinBox()
        self.am_freq_spin.setRange(0.01, 20000.0)
        self.am_freq_spin.setDecimals(3)
        self.am_freq_spin.setValue(5.0)
        self.am_freq_spin.valueChanged.connect(lambda v: self.update_param("am_frequency", v))
        am_layout.addRow(tr("Mod Freq (Hz):"), self.am_freq_spin)

        self.am_depth_spin = QDoubleSpinBox()
        self.am_depth_spin.setRange(0.0, 100.0)
        self.am_depth_spin.setDecimals(1)
        self.am_depth_spin.setSingleStep(1.0)
        self.am_depth_spin.setValue(50.0)
        self.am_depth_spin.setSuffix("%")
        self.am_depth_spin.valueChanged.connect(lambda v: self.update_param("am_depth", v))
        am_layout.addRow(tr("Depth (m):"), self.am_depth_spin)

        am_group.setLayout(am_layout)
        return am_group

    def _create_fm_tab(self):
        fm_group = QGroupBox(tr("FM (Frequency Modulation)"))
        fm_group.setCheckable(True)
        fm_group.setChecked(False)
        fm_group.toggled.connect(lambda v: self.update_param("fm_enabled", v))
        self.fm_group = fm_group

        fm_layout = QFormLayout()

        self.fm_freq_spin = QDoubleSpinBox()
        self.fm_freq_spin.setRange(0.01, 20000.0)
        self.fm_freq_spin.setDecimals(3)
        self.fm_freq_spin.setValue(5.0)
        self.fm_freq_spin.valueChanged.connect(lambda v: self.update_param("fm_frequency", v))
        fm_layout.addRow(tr("Mod Freq (Hz):"), self.fm_freq_spin)

        self.fm_dev_spin = QDoubleSpinBox()
        self.fm_dev_spin.setRange(0.0, 20000.0)
        self.fm_dev_spin.setDecimals(3)
        self.fm_dev_spin.setValue(100.0)
        self.fm_dev_spin.valueChanged.connect(lambda v: self.update_param("fm_deviation", v))
        fm_layout.addRow(tr("Deviation Δf (Hz):"), self.fm_dev_spin)

        fm_group.setLayout(fm_layout)
        return fm_group

    def _create_pm_tab(self):
        pm_group = QGroupBox(tr("ΦM (Phase Modulation)"))
        pm_group.setCheckable(True)
        pm_group.setChecked(False)
        pm_group.toggled.connect(lambda v: self.update_param("pm_enabled", v))
        self.pm_group = pm_group

        pm_layout = QFormLayout()

        self.pm_freq_spin = QDoubleSpinBox()
        self.pm_freq_spin.setRange(0.01, 20000.0)
        self.pm_freq_spin.setDecimals(3)
        self.pm_freq_spin.setValue(5.0)
        self.pm_freq_spin.valueChanged.connect(lambda v: self.update_param("pm_frequency", v))
        pm_layout.addRow(tr("Mod Freq (Hz):"), self.pm_freq_spin)

        self.pm_dev_spin = QDoubleSpinBox()
        self.pm_dev_spin.setRange(0.0, 180.0)
        self.pm_dev_spin.setDecimals(3)
        self.pm_dev_spin.setValue(30.0)
        self.pm_dev_spin.valueChanged.connect(lambda v: self.update_param("pm_deviation_deg", v))
        pm_layout.addRow(tr("Deviation Δφ (deg):"), self.pm_dev_spin)

        pm_group.setLayout(pm_layout)
        return pm_group

    def get_active_params_list(self):
        if self.current_target == "L":
            return [self.module.params_L]
        elif self.current_target == "R":
            return [self.module.params_R]
        elif self.current_target == "LINK":
            return [self.module.params_L, self.module.params_R]
        return []

    def update_param(self, name, value):
        for p in self.get_active_params_list():
            self.module.update_param(p, name, value)

        # If linked, we might need to refresh UI if we just set both?
        # No, UI reflects the state. If linked, we assume they are now same.

    def load_params_to_ui(self, params: SignalParameters):
        # Block signals to prevent feedback loops
        self.block_all_signals(True)

        waveform_key = params.waveform
        if params.waveform == "burst" and bool(getattr(params, "burst_windowed", False)):
            waveform_key = "burst_windowed"
        self._set_wave_combo_key(waveform_key)
        self.noise_combo.setCurrentText(params.noise_color)
        self.mt_count_spin.setValue(params.multitone_count)
        self.mls_order_combo.setCurrentText(str(params.mls_order))
        self.burst_on_spin.setValue(params.burst_on_cycles)
        self.burst_off_spin.setValue(params.burst_off_cycles)
        self.pulse_width_spin.setValue(params.pulse_width)
        self.saw_type_combo.setCurrentText(params.sawtooth_type)
        self.noise_amp_spin.setValue(params.noise_amplitude)
        self.prbs_order_combo.setCurrentText(str(params.prbs_order))
        if hasattr(self, "prbs_seed_spin"):
            self.prbs_seed_spin.setValue(params.prbs_seed)

        self.freq_spin.setValue(params.frequency)
        self.freq_slider.setValue(self._freq_to_slider(params.frequency))
        
        self.cal_check.setChecked(getattr(params, "use_freq_cal", False))

        self.phase_spin.setValue(params.phase_offset)
        self.phase_slider.setValue(int(params.phase_offset))

        self.delay_spin.setValue(float(getattr(params, "delay_ms", 0.0)))
        self.delay_slider.setValue(int(round(float(getattr(params, "delay_ms", 0.0)) * 1000.0)))

        self.update_amp_display_value(params.amplitude)

        self.sweep_group.setChecked(params.sweep_enabled)
        self.start_freq_spin.setValue(params.start_freq)
        self.end_freq_spin.setValue(params.end_freq)
        self.duration_spin.setValue(params.sweep_duration)
        self.log_check.setChecked(params.log_sweep)

        # Filter params
        self.lpf_group.setChecked(params.lpf_enabled)
        self.lpf_freq_spin.setValue(params.lpf_freq)
        self.lpf_order_spin.setValue(params.lpf_order)

        self.hpf_group.setChecked(params.hpf_enabled)
        self.hpf_freq_spin.setValue(params.hpf_freq)
        self.hpf_order_spin.setValue(params.hpf_order)

        self.am_group.setChecked(getattr(params, "am_enabled", False))
        self.am_freq_spin.setValue(getattr(params, "am_frequency", 5.0))
        self.am_depth_spin.setValue(getattr(params, "am_depth", 50.0))

        self.fm_group.setChecked(params.fm_enabled)
        self.fm_freq_spin.setValue(params.fm_frequency)
        self.fm_dev_spin.setValue(params.fm_deviation)

        self.pm_group.setChecked(params.pm_enabled)
        self.pm_freq_spin.setValue(params.pm_frequency)
        self.pm_dev_spin.setValue(params.pm_deviation_deg)

        self.snap_check.setChecked(params.bin_center_snap)
        self.fft_size_combo.setEnabled(params.bin_center_snap)
        self._set_fft_size_combo(params.fft_size)

        self._apply_waveform_key(waveform_key, update_params=False)  # Update visibility

        self.block_all_signals(False)

    def block_all_signals(self, block):
        widgets = [
            self.wave_combo,
            self.noise_combo,
            self.mt_count_spin,
            self.mls_order_combo,
            self.burst_on_spin,
            self.burst_off_spin,
            self.pulse_width_spin,
            self.saw_type_combo,
            self.noise_amp_spin,
            self.prbs_order_combo,
            self.prbs_seed_spin,
            self.freq_spin,
            self.freq_slider,
            self.cal_check,
            self.phase_spin,
            self.phase_slider,
            self.delay_spin,
            self.delay_slider,
            self.amp_spin,
            self.amp_slider,
            self.sweep_group,
            self.start_freq_spin,
            self.end_freq_spin,
            self.duration_spin,
            self.log_check,
            self.lpf_group,
            self.lpf_freq_spin,
            self.lpf_order_spin,
            self.hpf_group,
            self.hpf_freq_spin,
            self.hpf_order_spin,
            self.am_group,
            self.am_freq_spin,
            self.am_depth_spin,
            self.fm_group,
            self.fm_freq_spin,
            self.fm_dev_spin,
            self.pm_group,
            self.pm_freq_spin,
            self.pm_dev_spin,
            self.snap_check,
            self.fft_size_combo,
        ]
        for w in widgets:
            w.blockSignals(block)

    def on_target_changed(self, btn):
        if self.target_l.isChecked():
            self.current_target = "L"
            self.load_params_to_ui(self.module.params_L)
        elif self.target_r.isChecked():
            self.current_target = "R"
            self.load_params_to_ui(self.module.params_R)
        elif self.target_link.isChecked():
            self.current_target = "LINK"
            # When switching to link, copy L to R (or vice versa, let's say L is master)
            # Or just load L to UI, and next edit updates both.
            # Let's copy L to R immediately to ensure consistency
            self.copy_params(self.module.params_L, self.module.params_R)
            self.load_params_to_ui(self.module.params_L)

    def copy_params(self, src, dst):
        dst.waveform = src.waveform
        dst.frequency = src.frequency
        dst.use_freq_cal = getattr(src, "use_freq_cal", False)
        dst.amplitude = src.amplitude
        dst.noise_color = src.noise_color
        dst.fm_enabled = src.fm_enabled
        dst.fm_frequency = src.fm_frequency
        dst.fm_deviation = src.fm_deviation
        dst.pm_enabled = src.pm_enabled
        dst.pm_frequency = src.pm_frequency
        dst.pm_deviation_deg = src.pm_deviation_deg
        dst.am_enabled = src.am_enabled
        dst.am_frequency = src.am_frequency
        dst.am_depth = src.am_depth
        dst.sweep_enabled = src.sweep_enabled
        dst.start_freq = src.start_freq
        dst.end_freq = src.end_freq
        dst.sweep_duration = src.sweep_duration
        dst.log_sweep = src.log_sweep
        dst.lpf_enabled = src.lpf_enabled
        dst.lpf_freq = src.lpf_freq
        dst.lpf_order = src.lpf_order
        dst.hpf_enabled = src.hpf_enabled
        dst.hpf_freq = src.hpf_freq
        dst.hpf_order = src.hpf_order
        dst.multitone_count = src.multitone_count
        dst.mls_order = src.mls_order
        dst.burst_on_cycles = src.burst_on_cycles
        dst.burst_off_cycles = src.burst_off_cycles
        dst.burst_windowed = src.burst_windowed
        dst.pulse_width = src.pulse_width
        dst.sawtooth_type = src.sawtooth_type
        dst.noise_amplitude = src.noise_amplitude
        dst.phase_offset = src.phase_offset
        dst.delay_ms = src.delay_ms
        dst.prbs_order = src.prbs_order
        dst.prbs_seed = src.prbs_seed
        dst.bin_center_snap = src.bin_center_snap
        dst.fft_size = src.fft_size

    def on_route_changed(self, btn):
        if self.route_l.isChecked():
            self.module.output_mode = "L"
        elif self.route_r.isChecked():
            self.module.output_mode = "R"
        elif self.route_stereo.isChecked():
            self.module.output_mode = "STEREO"

    def on_snap_toggled(self, checked):
        self.update_param("bin_center_snap", checked)
        self.fft_size_combo.setEnabled(checked)
        # Re-apply frequency to snap it if enabled
        current_freq = self.freq_spin.value()
        self.on_freq_spin_changed(current_freq)

    def on_fft_size_changed(self, text):
        try:
            val = int(text)
            if val > 0:
                self.update_param("fft_size", val)
                # Re-apply frequency to snap with new size
                current_freq = self.freq_spin.value()
                self.on_freq_spin_changed(current_freq)
        except ValueError:
            pass

    def on_wave_changed(self, _index):
        key = self.wave_combo.currentData() or self.wave_combo.currentText()
        self._apply_waveform_key(str(key), update_params=True)

        # Refix RMS if unit is maintaining RMS
        unit = self.unit_combo.currentText()
        if unit in ["Vrms", "dBu", "dBV"]:
            # Value in spinner is the desired RMS.
            # We must update peak amplitude to match this RMS with new crest factor.
            self.on_amp_spin_changed(self.amp_spin.value())

    # --- Frequency Helpers ---
    def _freq_to_slider(self, freq):
        return int(1000 * (np.log10(freq) - np.log10(20)) / (np.log10(20000) - np.log10(20)))

    def _slider_to_freq(self, val):
        log_freq = np.log10(20) + (val / 1000) * (np.log10(20000) - np.log10(20))
        return 10**log_freq

    def _get_snapped_frequency(self, freq):
        # Check if snapping is enabled in the active params
        # We look at the first active param set (L or R)
        params_list = self.get_active_params_list()
        if not params_list:
            return freq

        params = params_list[0]
        if not params.bin_center_snap:
            return freq

        sample_rate = self.module.audio_engine.sample_rate
        if sample_rate <= 0 or params.fft_size <= 0:
            return freq

        bin_width = sample_rate / params.fft_size

        # Calculate nearest bin index
        # f = k * bin_width
        k = round(freq / bin_width)
        snapped_freq = k * bin_width

        # Ensure we don't snap to 0 if the user didn't intend to (though 0 is a valid bin center DC)
        # But for audio signal generator, usually we want > 0. 
        # But let's respect the math. If freq is close to 0, it snaps to DC.

        return snapped_freq

    def on_freq_spin_changed(self, val):
        snapped_val = self._get_snapped_frequency(val)

        self.update_param("frequency", snapped_val)

        # Block signals to update UI without recursion
        self.freq_spin.blockSignals(True)
        self.freq_slider.blockSignals(True)

        if snapped_val != val:
            self.freq_spin.setValue(snapped_val)

        self.freq_slider.setValue(self._freq_to_slider(snapped_val if snapped_val > 0 else 20))

        self.freq_spin.blockSignals(False)
        self.freq_slider.blockSignals(False)

    def on_freq_slider_changed(self, val):
        freq = self._slider_to_freq(val)
        snapped_freq = self._get_snapped_frequency(freq)

        self.update_param("frequency", snapped_freq)

        self.freq_spin.blockSignals(True)
        self.freq_slider.blockSignals(True)

        self.freq_spin.setValue(snapped_freq)
        # We don't necessarily update the slider value back from snapped freq here 
        # because it might make the slider 'jumpy' while dragging. 
        # But to be consistent with the spin box, we probably should if the snap is large.
        # For smooth checking, maybe only update slider if we released handle? 
        # For now, let's keep slider smooth but actual param snapped.
        # Actually, if we don't update slider, it might be out of sync.
        # Let's update it.
        if snapped_freq != freq:
             self.freq_slider.setValue(self._freq_to_slider(snapped_freq if snapped_freq > 0 else 20))

        self.freq_spin.blockSignals(False)
        self.freq_slider.blockSignals(False)

    def on_phase_spin_changed(self, val):
        self.update_param("phase_offset", val)
        self.phase_slider.blockSignals(True)
        self.phase_slider.setValue(int(val))
        self.phase_slider.blockSignals(False)

    def on_phase_slider_changed(self, val):
        self.update_param("phase_offset", float(val))
        self.phase_spin.blockSignals(True)
        self.phase_spin.setValue(float(val))
        self.phase_spin.blockSignals(False)

    def on_delay_spin_changed(self, val):
        self.update_param("delay_ms", float(val))
        self.delay_slider.blockSignals(True)
        self.delay_slider.setValue(int(round(float(val) * 1000.0)))
        self.delay_slider.blockSignals(False)

    def on_delay_slider_changed(self, val):
        ms = float(val) / 1000.0
        self.update_param("delay_ms", ms)
        self.delay_spin.blockSignals(True)
        self.delay_spin.setValue(ms)
        self.delay_spin.blockSignals(False)

    # --- Amplitude Helpers ---
    def on_unit_changed(self, unit):
        # Refresh display with current amplitude in new unit
        # We need to know the current amplitude.
        # Since we might be in LINK mode, we take from L (assuming synced) or just the first active.
        params = self.get_active_params_list()[0]
        self.update_amp_display_value(params.amplitude)

    def update_amp_display_value(self, amp_0_1):
        unit = self.unit_combo.currentText()
        gain = self.module.audio_engine.calibration.output_gain

        self.amp_spin.blockSignals(True)

        cf = self._get_current_crest_factor()

        if unit == "Linear (0-1)":
            self.amp_spin.setRange(0, 1.0)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setValue(amp_0_1)
        elif unit == "dBFS":
            self.amp_spin.setRange(-120, 0)
            self.amp_spin.setSingleStep(1.0)
            val = 20 * np.log10(amp_0_1 + 1e-12)
            self.amp_spin.setValue(val)
        elif unit == "dBV":
            v_peak = amp_0_1 * gain
            v_rms = v_peak / cf
            val = 20 * np.log10(v_rms + 1e-12)
            self.amp_spin.setRange(-120, 20)
            self.amp_spin.setSingleStep(1.0)
            self.amp_spin.setValue(val)
        elif unit == "dBu":
            v_peak = amp_0_1 * gain
            v_rms = v_peak / cf
            val = 20 * np.log10((v_rms + 1e-12) / 0.7746)
            self.amp_spin.setRange(-120, 20)
            self.amp_spin.setSingleStep(1.0)
            self.amp_spin.setValue(val)
        elif unit == "Vrms":
            v_peak = amp_0_1 * gain
            v_rms = v_peak / cf
            self.amp_spin.setRange(0, 100)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setValue(v_rms)
        elif unit == "Vpeak":
            v_peak = amp_0_1 * gain
            self.amp_spin.setRange(0, 100)
            self.amp_spin.setSingleStep(0.1)
            self.amp_spin.setValue(v_peak)

        self.amp_spin.blockSignals(False)

        self.amp_slider.blockSignals(True)
        self.amp_slider.setValue(int(amp_0_1 * 100))
        self.amp_slider.blockSignals(False)

    def on_amp_spin_changed(self, val):
        unit = self.unit_combo.currentText()
        gain = self.module.audio_engine.calibration.output_gain
        amp_0_1 = 0.0

        if unit == "Linear (0-1)":
            amp_0_1 = val
        elif unit == "dBFS":
            amp_0_1 = 10 ** (val / 20)
        elif unit == "dBV":
            v_rms = 10 ** (val / 20)
            v_peak = v_rms * self._get_current_crest_factor()
            amp_0_1 = v_peak / gain
        elif unit == "dBu":
            v_rms = 0.7746 * 10 ** (val / 20)
            v_peak = v_rms * self._get_current_crest_factor()
            amp_0_1 = v_peak / gain
        elif unit == "Vrms":
            v_peak = val * self._get_current_crest_factor()
            amp_0_1 = v_peak / gain
        elif unit == "Vpeak":
            amp_0_1 = val / gain

        if amp_0_1 > 1.0:
            amp_0_1 = 1.0
        elif amp_0_1 < 0.0:
            amp_0_1 = 0.0

        self.update_param("amplitude", amp_0_1)

        self.amp_slider.blockSignals(True)
        self.amp_slider.setValue(int(amp_0_1 * 100))
        self.amp_slider.blockSignals(False)

    def on_amp_slider_changed(self, val):
        amp = val / 100.0
        self.update_param("amplitude", amp)
        self.update_amp_display_value(amp)

    def on_toggle(self, checked):
        if checked:
            self.module.start_generation()
            self.toggle_btn.setText(tr("Stop Output"))
        else:
            self.module.stop_generation()
            self.toggle_btn.setText(tr("Start Output"))

    def _get_current_crest_factor(self):
        """Returns the Crest Factor (Peak / RMS) for the current waveform."""
        key = self.wave_combo.currentData() or self.wave_combo.currentText()
        # Square, Pulse, MLS, PRBS (if full-swing -1..1) have Signal Power = Peak Power => CF=1
        if key in ["square", "pulse", "mls", "prbs"]:
            return 1.0
        # Triangle, Sawtooth have CF = sqrt(3)
        if key in ["triangle", "sawtooth"]:
            import numpy as np

            return np.sqrt(3.0)

        # Sine, Noise (approx), etc. default to standard sine convention (sqrt(2))
        import numpy as np

        return np.sqrt(2.0)
