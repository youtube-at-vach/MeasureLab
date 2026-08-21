import logging
import math
from dataclasses import dataclass, fields
from typing import Any, Optional, Tuple

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
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
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QToolButton,
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
from src.core.utils import amplitude_to_linear, format_si, linear_to_amplitude
from src.gui.widgets.instrument_controls import PreferredNumberSpinBox
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

    # Amplitude Sweep parameters
    amp_sweep_enabled: bool = False
    start_amp: float = 0.1
    end_amp: float = 1.0
    amp_sweep_duration: float = 5.0
    log_amp_sweep: bool = True

    # Filter Parameters (BPF/LPF/HPF/Notch)
    lpf_enabled: bool = False
    lpf_freq: float = 20000.0
    lpf_order: int = 4

    hpf_enabled: bool = False
    hpf_freq: float = 20.0
    hpf_order: int = 4

    notch_enabled: bool = False
    notch_freq: float = 1000.0
    notch_q: float = 30.0

    # Advanced Signal Parameters
    multitone_count: int = 10
    mls_order: int = 15
    golay_order: int = 12
    golay_pair: str = "A"
    burst_on_cycles: int = 10
    burst_off_cycles: int = 90
    burst_windowed: bool = False

    # New Parameters
    pulse_width: float = 50.0  # %
    impulse_samples: int = 1
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
    freq_cal_manual_ppm: float = 0.0

    # Internal state (not shared/copied usually, but kept here for simplicity per channel)
    _phase: float = 0.0
    _impulse_phase_samples: float = 0.0
    _sweep_time: float = 0.0
    _amp_sweep_time: float = 0.0
    _buffer: Optional[np.ndarray] = None
    _buffer_index: int = 0
    _buffer_cache_key: Optional[Tuple] = None
    _buffer_read_cache: Optional[np.ndarray] = None
    _buffer_read_cache_key: Optional[Tuple] = None

    # FM/phase-accumulator state (radians)
    _carrier_phase_rad: float = 0.0
    _fm_phase_rad: float = 0.0
    _pm_phase_rad: float = 0.0
    _am_phase_rad: float = 0.0

    # Filter cache
    _lpf_sos: Optional[np.ndarray] = None
    _lpf_cache_key: Optional[Tuple] = None
    _hpf_sos: Optional[np.ndarray] = None
    _hpf_cache_key: Optional[Tuple] = None
    _notch_sos: Optional[np.ndarray] = None
    _notch_cache_key: Optional[Tuple] = None

    # Combined filter cache. Keeping the cascade in one SOS array avoids
    # repeating scipy's validation/axis setup once per enabled filter.
    _combined_sos: Optional[np.ndarray] = None
    _combined_filter_cache_key: Optional[Tuple] = None
    _combined_zi: Optional[np.ndarray] = None

    # Reused fixed-frequency phase work area for the real-time callback.
    _phase_work: Optional[np.ndarray] = None


class SignalGenerator(MeasurementModule):
    BUFFERED_WAVEFORMS = ["noise", "multitone", "mls", "golay", "burst", "prbs"]
    SHAREABLE_BUFFERED_WAVEFORMS = {"multitone", "mls", "golay", "burst", "prbs"}
    PERIODIC_WAVEFORMS = {"sine", "square", "triangle", "sawtooth", "pulse", "tone_noise"}

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine

        self.params_L = SignalParameters()
        self.params_R = SignalParameters()
        self._golay_cache: dict[tuple[int, str], np.ndarray] = {}
        self._sample_offsets: Optional[np.ndarray] = None
        self._sample_offsets_frames = 0
        self._block_time: Optional[np.ndarray] = None
        self._block_time_key: Optional[tuple[int, float]] = None

        # Output Routing: 'L', 'R', 'STEREO'
        self._output_mode = "STEREO"

        self.is_playing = False
        self.callback_id = None
        self.output_overload_latched = {"L": False, "R": False}
        self.output_peak = {"L": 0.0, "R": 0.0}

    @property
    def output_mode(self) -> str:
        return self._output_mode

    @output_mode.setter
    def output_mode(self, mode: str):
        if mode not in {"L", "R", "STEREO"}:
            raise ValueError(f"Unsupported signal generator output mode: {mode}")

        if self.is_playing and mode != self._output_mode:
            sample_rate = float(self.audio_engine.sample_rate)
            for params in self._params_for_output_mode(mode):
                if params.waveform in self.BUFFERED_WAVEFORMS:
                    self._prepare_buffer(params, sample_rate)

        self._output_mode = mode

    def _params_for_output_mode(self, mode: Optional[str] = None) -> tuple[SignalParameters, ...]:
        mode = self._output_mode if mode is None else mode
        if mode == "L":
            return (self.params_L,)
        if mode == "R":
            return (self.params_R,)
        return (self.params_L, self.params_R)

    def _get_sample_offsets(self, frames: int) -> np.ndarray:
        if self._sample_offsets is None or self._sample_offsets_frames != frames:
            self._sample_offsets = np.arange(frames, dtype=np.float64)
            self._sample_offsets_frames = frames
            self._block_time = None
            self._block_time_key = None
        return self._sample_offsets

    def _get_block_time(self, frames: int, sample_rate: float) -> np.ndarray:
        key = (frames, float(sample_rate))
        if self._block_time is None or self._block_time_key != key:
            self._block_time = self._get_sample_offsets(frames) / sample_rate
            self._block_time_key = key
        return self._block_time

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
                base_cal = 1.0 / val if val > 0 else 1.0
            else:
                val = getattr(cal, "frequency_calibration", 1.0)
                base_cal = 1.0 / val if val > 0 else 1.0

            ppm_adj = getattr(params, "freq_cal_manual_ppm", 0.0)
            return base_cal * (1.0 + ppm_adj / 1_000_000.0)
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
        # The project uses scipy for audio operations, we can just use scipy.signal.max_len_seq directly
        # and not have a large bitwise fallback loop at all.
        import scipy.signal

        order = params.mls_order
        if not (2 <= order <= 32):
            order = 15

        # We pass state as an int8 numpy array to ensure consistency
        # and prevent recreating Python lists internally in scipy if needed.
        # However max_len_seq defaults state to [1]*nbits so passing None is also fine.
        seq, state = scipy.signal.max_len_seq(order)
        signal = seq.astype(float) * 2.0 - 1.0
        return signal

    def _generate_golay(self, params: SignalParameters, sample_rate):
        """Generates a Golay complementary sequence for the selected pair."""
        del sample_rate  # Precomputed sequence is sample-rate independent.

        order = int(np.clip(getattr(params, "golay_order", 12), 1, 20))
        pair = "B" if str(getattr(params, "golay_pair", "A")).upper() == "B" else "A"
        cache_key = (order, pair)

        cached = self._golay_cache.get(cache_key)
        if cached is not None:
            return cached

        seq_a = np.ones(1, dtype=np.float32)
        seq_b = np.ones(1, dtype=np.float32)

        for _ in range(order):
            half = seq_a.size
            next_a = np.empty(half * 2, dtype=np.float32)
            next_b = np.empty(half * 2, dtype=np.float32)

            next_a[:half] = seq_a
            next_a[half:] = seq_b
            next_b[:half] = seq_a
            next_b[half:] = -seq_b

            seq_a = next_a
            seq_b = next_b

        signal = seq_a if pair == "A" else seq_b
        self._golay_cache[cache_key] = signal
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
                # Keep PRBS generation deterministic without resetting NumPy's
                # process-wide RNG, which may be in use by another audio client.
                rng = np.random.RandomState(params.prbs_seed)
                # Ensure at least one non-zero
                state = rng.randint(0, 2, size=order, dtype=np.int8)
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

    def _get_buffer_cache_key(self, params: SignalParameters, sample_rate: float) -> Optional[Tuple]:
        """Return every input that can change the selected buffered waveform."""
        waveform = params.waveform
        sample_rate = float(sample_rate)

        if waveform == "noise":
            return (waveform, params.noise_color, sample_rate, self._get_cal_factor(params))
        if waveform == "multitone":
            return (
                waveform,
                params.multitone_count,
                params.start_freq,
                params.end_freq,
                sample_rate,
                self._get_cal_factor(params),
            )
        if waveform == "mls":
            return (waveform, params.mls_order)
        if waveform == "golay":
            return (waveform, params.golay_order, params.golay_pair)
        if waveform == "burst":
            return (
                waveform,
                params.frequency,
                params.burst_on_cycles,
                params.burst_off_cycles,
                params.burst_windowed,
                sample_rate,
                self._get_cal_factor(params),
            )
        if waveform == "prbs":
            return (waveform, params.prbs_order, params.prbs_seed)
        return None

    def _prepare_buffer(self, params: SignalParameters, sample_rate):
        cache_key = self._get_buffer_cache_key(params, sample_rate)

        # Deterministic buffers are immutable after construction. Identical L/R
        # settings can therefore share their samples while retaining independent
        # read indices and modulation/filter state. Noise intentionally remains
        # independent between channels.
        if params.waveform in self.SHAREABLE_BUFFERED_WAVEFORMS:
            for other in (self.params_L, self.params_R):
                if other is params:
                    continue
                if other._buffer is not None and other._buffer_cache_key == cache_key:
                    params._buffer = other._buffer
                    params._buffer_cache_key = cache_key
                    params._buffer_index = 0
                    params._buffer_read_cache = None
                    params._buffer_read_cache_key = None
                    return

        if params._buffer is not None and params._buffer_cache_key == cache_key:
            params._buffer_index = 0
            return

        buffer = None
        if params.waveform == "noise":
            buffer = self._generate_noise_buffer(params, sample_rate)
        elif params.waveform == "multitone":
            buffer = self._generate_multitone(params, sample_rate)
        elif params.waveform == "mls":
            buffer = self._generate_mls(params, sample_rate)
        elif params.waveform == "golay":
            buffer = self._generate_golay(params, sample_rate)
        elif params.waveform == "burst":
            buffer = self._generate_burst(params, sample_rate)
        elif params.waveform == "prbs":
            buffer = self._generate_prbs(params, sample_rate)

        params._buffer = buffer
        params._buffer_cache_key = cache_key
        params._buffer_index = 0
        params._buffer_read_cache = None
        params._buffer_read_cache_key = None

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

                sos = scipy.signal.butter(order, freq, btype="low", fs=sample_rate, output="sos")
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

                sos = scipy.signal.butter(order, freq, btype="high", fs=sample_rate, output="sos")
                params._hpf_sos = sos
                params._hpf_cache_key = current_key
                return sos

            elif filter_type == "notch":
                freq = params.notch_freq
                q = params.notch_q
                current_key = (freq, q, sample_rate, "notch")

                if params._notch_sos is not None and params._notch_cache_key == current_key:
                    return params._notch_sos

                nyquist = sample_rate / 2.0
                if freq <= 0 or freq >= nyquist or q <= 0:
                    params._notch_sos = None
                    params._notch_cache_key = None
                    return None

                b, a = scipy.signal.iirnotch(freq, q, fs=sample_rate)
                sos = scipy.signal.tf2sos(b, a)

                params._notch_sos = sos
                params._notch_cache_key = current_key
                return sos

            return None

        except Exception:
            # logger.warning(f"Filter calculation failed: {e}")
            return None

    def _get_combined_filter_sos(self, params: SignalParameters, sample_rate: float):
        """Build one cached SOS cascade for every enabled output filter."""
        cache_key = (
            bool(params.lpf_enabled),
            params.lpf_order if params.lpf_enabled else None,
            params.lpf_freq if params.lpf_enabled else None,
            bool(params.hpf_enabled),
            params.hpf_order if params.hpf_enabled else None,
            params.hpf_freq if params.hpf_enabled else None,
            bool(params.notch_enabled),
            params.notch_freq if params.notch_enabled else None,
            params.notch_q if params.notch_enabled else None,
            float(sample_rate),
        )
        if params._combined_filter_cache_key == cache_key:
            return params._combined_sos

        sections = []
        if params.lpf_enabled:
            sos = self._get_filter_sos(params, "low", sample_rate)
            if sos is not None:
                sections.append(sos)
        if params.hpf_enabled:
            sos = self._get_filter_sos(params, "high", sample_rate)
            if sos is not None:
                sections.append(sos)
        if params.notch_enabled:
            sos = self._get_filter_sos(params, "notch", sample_rate)
            if sos is not None:
                sections.append(sos)

        params._combined_sos = np.concatenate(sections, axis=0) if sections else None
        params._combined_filter_cache_key = cache_key
        return params._combined_sos

    def _generate_wave_from_phase(self, params: SignalParameters, phase_rad: np.ndarray) -> np.ndarray:
        """
        Helper to generate waveform samples from a phase array (in radians).
        Handles sine, square, triangle, sawtooth, pulse, tone_noise.
        """
        offset_rad = np.radians(params.phase_offset)

        if params.waveform == "sine":
            signal = np.add(phase_rad, offset_rad)
            np.sin(signal, out=signal)
            signal *= params.amplitude
            return signal

        elif params.waveform == "square":
            signal = np.add(phase_rad, offset_rad)
            np.sin(signal, out=signal)
            np.sign(signal, out=signal)
            signal *= params.amplitude
            return signal

        elif params.waveform == "tone_noise":
            signal = np.add(phase_rad, offset_rad)
            np.sin(signal, out=signal)
            signal *= params.amplitude
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

    def _get_phase_work(self, params: SignalParameters, frames: int) -> np.ndarray:
        if params._phase_work is None or params._phase_work.size != frames:
            params._phase_work = np.empty(frames, dtype=np.float64)
        return params._phase_work

    def _write_fixed_periodic_signal(
        self,
        params: SignalParameters,
        frames: int,
        sample_rate_eff: float,
        destination: np.ndarray,
    ):
        """Write an unmodulated periodic waveform directly to an output channel."""
        phase_step = 2.0 * np.pi * params.frequency / sample_rate_eff
        phase = self._get_phase_work(params, frames)
        np.multiply(self._get_sample_offsets(frames), phase_step, out=phase)
        phase += params._carrier_phase_rad + np.radians(params.phase_offset)

        params._phase += frames
        params._carrier_phase_rad = float(np.fmod(params._carrier_phase_rad + frames * phase_step, 2.0 * np.pi))

        if params.waveform == "sine":
            np.sin(phase, out=destination)
            destination *= params.amplitude
            return

        if params.waveform == "square":
            np.sin(phase, out=destination)
            np.sign(destination, out=destination)
            destination *= params.amplitude
            return

        if params.waveform == "tone_noise":
            np.sin(phase, out=destination)
            destination *= params.amplitude
            destination += params.noise_amplitude * np.random.uniform(-1, 1, size=frames)
            return

        # The remaining periodic waveforms operate on cycle position. The phase
        # work area is disposable for this block, so all transformations can be
        # done in place before the final cast into the audio-engine destination.
        phase /= 2.0 * np.pi
        np.remainder(phase, 1.0, out=phase)

        if params.waveform == "triangle":
            phase *= 2.0
            phase -= 1.0
            np.abs(phase, out=phase)
            phase *= 2.0
            phase -= 1.0
            np.multiply(phase, params.amplitude, out=destination)
        elif params.waveform == "sawtooth":
            phase *= 2.0
            phase -= 1.0
            if params.sawtooth_type == "Falling":
                phase *= -1.0
            np.multiply(phase, params.amplitude, out=destination)
        elif params.waveform == "pulse":
            destination.fill(-params.amplitude)
            destination[phase < params.pulse_width / 100.0] = params.amplitude

    def _generate_impulse_signal(self, params: SignalParameters, frames: int, sample_rate_eff: float) -> np.ndarray:
        """Generate a periodic impulse train while preserving the requested fractional frequency."""
        if params.frequency <= 0 or sample_rate_eff <= 0:
            return np.zeros(frames)

        period_samples = max(1.0, sample_rate_eff / params.frequency)
        impulse_samples = max(1.0, min(float(params.impulse_samples), period_samples))
        phase_offset_samples = (params.phase_offset / 360.0) * period_samples
        sample_positions = (
            params._impulse_phase_samples + self._get_sample_offsets(frames) + phase_offset_samples
        ) % period_samples
        params._impulse_phase_samples = float((params._impulse_phase_samples + frames) % period_samples)
        return params.amplitude * np.where(sample_positions < impulse_samples, 1.0, 0.0)

    def _calculate_phase_from_freq(self, params: SignalParameters, f_inst_hz: np.ndarray, sample_rate: float):
        """Integrate instantaneous frequency to phase (radians) with continuity across blocks."""
        # Prevent negative frequencies from flipping waveforms in unexpected ways.
        # Clamp to >= 0 Hz; users can set deviation to 0 if they want no FM.
        if f_inst_hz.size == 0:
            return np.zeros(0, dtype=float)

        dphi = np.maximum(f_inst_hz, 0.0)
        dphi *= (2.0 * np.pi) / sample_rate

        # phase[0] should start at current carrier phase.
        phase0 = float(params._carrier_phase_rad)
        phase = np.cumsum(dphi)
        total_phase_advance = float(phase[-1])
        phase += phase0 - dphi[0]

        # Advance phase accumulator for next block.
        params._carrier_phase_rad = phase0 + total_phase_advance
        # Keep bounded to avoid numerical growth.
        params._carrier_phase_rad = float(np.fmod(params._carrier_phase_rad, 2.0 * np.pi))
        return phase

    def _apply_am(
        self, x: np.ndarray, params: SignalParameters, t_global_eff: np.ndarray, sample_rate_eff: float
    ) -> np.ndarray:
        """Apply simple AM (DSB-LC) envelope: x(t) * (1 + m*sin(2π*f_am*t))."""
        if not (params.am_enabled and params.am_frequency > 0 and params.am_depth != 0):
            return x

        m = float(np.clip(params.am_depth, 0.0, 100.0)) / 100.0
        if m == 0.0:
            return x

        frames = len(x)
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

    def _apply_filters(self, x: np.ndarray, params: SignalParameters, sample_rate_eff: float) -> np.ndarray:
        """Apply every enabled filter as one cached SOS cascade."""
        if scipy is None or not (params.lpf_enabled or params.hpf_enabled or params.notch_enabled):
            return x

        sos = self._get_combined_filter_sos(params, sample_rate_eff)
        if sos is None:
            return x

        state_shape = (sos.shape[0], 2)
        if params._combined_zi is None or params._combined_zi.shape != state_shape:
            params._combined_zi = np.zeros(state_shape, dtype=np.result_type(sos.dtype, x.dtype))

        y, params._combined_zi = scipy.signal.sosfilt(sos, x, zi=params._combined_zi)
        return y

    def _generate_buffered_signal(
        self, params: SignalParameters, frames, base_sample_rate, t_global_eff, sample_rate_eff
    ):
        del t_global_eff, sample_rate_eff
        buf = params._buffer
        if buf is None or len(buf) == 0:
            return np.zeros(frames)

        # For burst, support per-channel fractional delay at readout time.
        # This avoids rebuilding buffers and lets users adjust delay live.
        if params.waveform == "burst" and getattr(params, "delay_ms", 0.0) != 0.0:
            buf_len = len(buf)
            delay_samples = float(params.delay_ms) * float(base_sample_rate) / 1000.0
            # Use remainder + explicit wrapping to avoid rare float edge cases
            # where floor(idx) can equal buf_len.
            idx = np.remainder(
                float(params._buffer_index) + self._get_sample_offsets(frames) - delay_samples,
                float(buf_len),
            )

            floor_idx = np.floor(idx)
            i0 = np.mod(floor_idx.astype(np.int64, copy=False), buf_len)
            frac = idx - floor_idx
            i1 = (i0 + 1) % buf_len

            signal = (1.0 - frac) * buf[i0] + frac * buf[i1]
            params._buffer_index = int((params._buffer_index + frames) % buf_len)
            signal *= params.amplitude
            return signal

        buf_len = len(buf)
        start = params._buffer_index
        params._buffer_index = int((start + frames) % buf_len)

        if buf_len < frames:
            # Small MLS/Golay/PRBS orders may wrap dozens of times in one audio
            # block. Expand one cached read window so the real-time path becomes
            # a single slice instead of a Python loop per wrap.
            cache_key = (id(buf), frames)
            if params._buffer_read_cache is None or params._buffer_read_cache_key != cache_key:
                params._buffer_read_cache = np.resize(buf, frames + buf_len - 1)
                params._buffer_read_cache_key = cache_key
            chunk = params._buffer_read_cache[start : start + frames]
        elif start + frames <= buf_len:
            chunk = buf[start : start + frames]
        else:
            first = buf_len - start
            signal = np.empty(frames, dtype=buf.dtype)
            signal[:first] = buf[start:]
            signal[first:] = buf[: frames - first]
            chunk = signal

        if params.amplitude == 1.0:
            return chunk
        return chunk * params.amplitude

    def _generate_sweep_signal(self, params: SignalParameters, frames, t_global_eff, sample_rate_eff):
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
            phase = self._calculate_phase_from_freq(params, f_inst, sample_rate_eff)

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
            return signal

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
        return signal

    def _generate_standard_signal(self, params: SignalParameters, frames, t_global_eff, sample_rate_eff):
        if params.waveform == "impulse":
            return self._generate_impulse_signal(params, frames, sample_rate_eff)

        # Standard waveforms
        # Optional ΦM (works for periodic waveforms only)
        use_pm = bool(
            params.pm_enabled
            and params.pm_frequency > 0
            and params.pm_deviation_deg != 0
            and params.waveform in self.PERIODIC_WAVEFORMS
        )

        # Optional FM (works for periodic waveforms only)
        use_fm = bool(
            params.fm_enabled
            and params.fm_frequency > 0
            and params.fm_deviation != 0
            and params.waveform in self.PERIODIC_WAVEFORMS
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
            phase = self._calculate_phase_from_freq(params, f_inst, sample_rate_eff)

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
            # Fixed-frequency phase calculation with continuous phase tracking
            phase_step = 2.0 * np.pi * params.frequency / sample_rate_eff
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

                # Base phase is built continuously using phase_step
                base_phase = self._get_phase_work(params, frames)
                np.multiply(self._get_sample_offsets(frames), phase_step, out=base_phase)
                base_phase += params._carrier_phase_rad
                params._carrier_phase_rad = float(np.fmod(params._carrier_phase_rad + frames * phase_step, 2.0 * np.pi))

                phase = base_phase + beta * np.sin(pm_phase)
                signal = self._generate_wave_from_phase(params, phase)
                return signal

            phase_rad = self._get_phase_work(params, frames)
            np.multiply(self._get_sample_offsets(frames), phase_step, out=phase_rad)
            phase_rad += params._carrier_phase_rad
            params._carrier_phase_rad = float(np.fmod(params._carrier_phase_rad + frames * phase_step, 2.0 * np.pi))
            signal = self._generate_wave_from_phase(params, phase_rad)

        return signal

    def _generate_channel_signal(self, params: SignalParameters, frames, t_global, base_sample_rate):
        cal_factor = self._get_cal_factor(params)

        # Use effective parameters for clean continuous generation
        sample_rate_eff = base_sample_rate / cal_factor if cal_factor > 0 else base_sample_rate
        t_global_eff = t_global if cal_factor == 1.0 else t_global * cal_factor

        if params._buffer is not None:
            signal = self._generate_buffered_signal(params, frames, base_sample_rate, t_global_eff, sample_rate_eff)
        elif params.sweep_enabled:
            signal = self._generate_sweep_signal(params, frames, t_global_eff, sample_rate_eff)
        else:
            signal = self._generate_standard_signal(params, frames, t_global_eff, sample_rate_eff)

        # Amplitude Sweep
        if params.amp_sweep_enabled:
            t_block = params._amp_sweep_time + self._get_sample_offsets(frames) / sample_rate_eff
            t_mod = np.mod(t_block, params.amp_sweep_duration)

            if params.log_amp_sweep:
                start_amp_clean = max(1e-5, params.start_amp)
                end_amp_clean = max(1e-5, params.end_amp)
                start_db = 20.0 * np.log10(start_amp_clean)
                end_db = 20.0 * np.log10(end_amp_clean)
                db_env = start_db + (end_db - start_db) * (t_mod / params.amp_sweep_duration)
                amp_env = 10.0 ** (db_env / 20.0)
                if params.start_amp == 0.0:
                    amp_env = np.where(t_mod < 0.01, 0.0, amp_env)
                if params.end_amp == 0.0:
                    amp_env = np.where(t_mod > params.amp_sweep_duration - 0.01, 0.0, amp_env)
            else:
                amp_env = params.start_amp + (params.end_amp - params.start_amp) * (t_mod / params.amp_sweep_duration)

            if params.amplitude > 0.0:
                signal = (signal / params.amplitude) * amp_env
            else:
                signal = signal * amp_env

            params._amp_sweep_time += frames / sample_rate_eff
            params._amp_sweep_time = np.mod(params._amp_sweep_time, params.amp_sweep_duration)

        signal = self._apply_am(signal, params, t_global_eff, sample_rate_eff)
        signal = self._apply_filters(signal, params, sample_rate_eff)

        return signal

    def _can_write_standard_signal_directly(self, params: SignalParameters) -> bool:
        if params.waveform not in self.PERIODIC_WAVEFORMS:
            return False
        if params.sweep_enabled or params.amp_sweep_enabled:
            return False
        if params.lpf_enabled or params.hpf_enabled or params.notch_enabled:
            return False
        if params.am_enabled and params.am_frequency > 0 and params.am_depth != 0:
            return False
        if params.fm_enabled and params.fm_frequency > 0 and params.fm_deviation != 0:
            return False
        if params.pm_enabled and params.pm_frequency > 0 and params.pm_deviation_deg != 0:
            return False
        return True

    def _generate_channel_into(
        self,
        params: SignalParameters,
        frames: int,
        t_global: np.ndarray,
        base_sample_rate: float,
        destination: np.ndarray,
    ):
        if params._buffer is None and self._can_write_standard_signal_directly(params):
            cal_factor = self._get_cal_factor(params)
            sample_rate_eff = base_sample_rate / cal_factor if cal_factor > 0 else base_sample_rate
            self._write_fixed_periodic_signal(params, frames, sample_rate_eff, destination)
            return

        signal = self._generate_channel_signal(params, frames, t_global, base_sample_rate)
        np.copyto(destination, signal, casting="unsafe")

    def start_generation(self):
        if self.is_playing:
            return

        base_sample_rate = self.audio_engine.sample_rate
        self.output_overload_latched = {"L": False, "R": False}
        self.output_peak = {"L": 0.0, "R": 0.0}

        # Reset states
        for params in (self.params_L, self.params_R):
            params._phase = 0
            params._impulse_phase_samples = 0.0
            params._sweep_time = 0
            params._amp_sweep_time = 0.0
            params._carrier_phase_rad = 0.0
            params._fm_phase_rad = 0.0
            params._pm_phase_rad = 0.0
            params._am_phase_rad = 0.0
            params._combined_zi = None

        # Prepare only channels that can currently reach the output. Switching
        # routing during playback prepares the newly activated channel in the
        # output_mode setter, outside the real-time callback.
        for params in self._params_for_output_mode():
            self._prepare_buffer(params, base_sample_rate)

        def callback(indata, outdata, frames, time, status):
            if status:
                logger.debug(status)

            t = self._get_block_time(frames, base_sample_rate)
            outdata.fill(0)

            # Left Channel
            if self.output_mode in {"L", "STEREO"} and outdata.shape[1] >= 1:
                self._generate_channel_into(self.params_L, frames, t, base_sample_rate, outdata[:, 0])
                self._limit_channel_output(outdata[:, 0], "L")

            # Right Channel
            if self.output_mode in {"R", "STEREO"} and outdata.shape[1] >= 2:
                # If we are in STEREO but want to output the SAME signal if linked?
                # The user requirement says "L and R separate signals".
                # So we always use params_R for Right channel.
                # If the user wants them same, they copy settings in UI.
                self._generate_channel_into(self.params_R, frames, t, base_sample_rate, outdata[:, 1])
                self._limit_channel_output(outdata[:, 1], "R")

        try:
            callback_id = self.audio_engine.register_callback(callback)
        except Exception:
            self.callback_id = None
            self.is_playing = False
            raise

        self.callback_id = callback_id
        self.is_playing = True

    def _limit_channel_output(self, samples: np.ndarray, channel: str):
        """Latch generator overloads and keep this client's output inside full scale."""
        if samples.size == 0:
            return

        maximum = float(np.max(samples))
        minimum = float(np.min(samples))
        peak = max(abs(maximum), abs(minimum))
        if not math.isfinite(peak):
            self.output_overload_latched[channel] = True
            np.nan_to_num(samples, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
            maximum = float(np.max(samples))
            minimum = float(np.min(samples))
            peak = max(abs(maximum), abs(minimum))

        self.output_peak[channel] = max(self.output_peak[channel], peak)
        if peak > 1.0:
            self.output_overload_latched[channel] = True
            np.clip(samples, -1.0, 1.0, out=samples)

    def stop_generation(self):
        try:
            if self.callback_id is not None:
                callback_id = self.callback_id
                self.callback_id = None
                self.audio_engine.unregister_callback(callback_id)
        finally:
            self.is_playing = False

    def update_waveform(self, params: SignalParameters, waveform: str, sample_rate: float):
        """Updates the waveform type and regenerates/clears buffer if needed."""
        if params.sweep_enabled and waveform != "sine":
            waveform = "sine"
        if waveform not in self.PERIODIC_WAVEFORMS:
            params.fm_enabled = False
            params.pm_enabled = False
        params.waveform = waveform

        # Check if new waveform uses buffer
        if waveform in self.BUFFERED_WAVEFORMS:
            self._prepare_buffer(params, sample_rate)
        else:
            # Clear buffer so that standard generation logic is used
            params._buffer = None
            params._buffer_index = 0
            params._buffer_cache_key = None
            params._buffer_read_cache = None
            params._buffer_read_cache_key = None

    def update_param(self, params: SignalParameters, name: str, value: Any):
        """Updates a parameter and triggers buffer regeneration if necessary."""
        if name == "sweep_enabled" and bool(value) and params.waveform != "sine":
            self.update_waveform(params, "sine", self.audio_engine.sample_rate)

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

            if params.waveform == "noise" and name in {
                "noise_color",
                "use_freq_cal",
                "freq_cal_manual_ppm",
            }:
                needs_update = True
            elif params.waveform == "multitone" and name in {
                "multitone_count",
                "start_freq",
                "end_freq",
                "use_freq_cal",
                "freq_cal_manual_ppm",
            }:
                needs_update = True
            elif params.waveform == "mls" and name == "mls_order":
                needs_update = True
            elif params.waveform == "golay" and name in {"golay_order", "golay_pair"}:
                needs_update = True
            elif params.waveform == "burst" and name in {
                "frequency",
                "burst_on_cycles",
                "burst_off_cycles",
                "burst_windowed",
                "use_freq_cal",
                "freq_cal_manual_ppm",
            }:
                needs_update = True
            elif params.waveform == "prbs" and name in {"prbs_order", "prbs_seed"}:
                needs_update = True

            if needs_update:
                sample_rate = self.audio_engine.sample_rate
                self._prepare_buffer(params, sample_rate)


class SignalGeneratorWidget(QWidget):
    FREQUENCY_PARAM_NAMES = (
        "frequency",
        "start_freq",
        "end_freq",
        "lpf_freq",
        "hpf_freq",
        "notch_freq",
        "am_frequency",
        "fm_frequency",
        "pm_frequency",
    )
    FILTER_FREQUENCY_PARAM_NAMES = ("lpf_freq", "hpf_freq", "notch_freq")

    def __init__(self, module: SignalGenerator):
        super().__init__()
        self.module = module
        self.waveform_labels = {
            "sine": tr("Sine"),
            "square": tr("Square"),
            "triangle": tr("Triangle"),
            "sawtooth": tr("Sawtooth"),
            "pulse": tr("Pulse"),
            "impulse": tr("Impulse"),
            "tone_noise": tr("Tone + Noise"),
            "noise": tr("Noise"),
            "multitone": tr("Multitone"),
            "mls": tr("MLS"),
            "golay": tr("Golay"),
            "burst": tr("Burst"),
            "burst_windowed": tr("Burst (windowed)"),
            "prbs": tr("PRBS"),
        }
        self.current_target = "L"  # 'L', 'R', 'LINK'
        self._last_nyquist_freq: float | None = None
        self._last_output_calibration_signature: tuple[bool, float] | None = None
        self._output_error_message = ""
        self._current_theme_name = "light"
        self.init_ui()

        # Theme handling
        self.app = QApplication.instance()
        if hasattr(self.app, "theme_manager"):
            self.app.theme_manager.theme_changed.connect(self.apply_theme)
            self.apply_theme(self.app.theme_manager.get_current_theme())

        self.frequency_limit_timer = QTimer(self)
        self.frequency_limit_timer.setInterval(1000)
        self.frequency_limit_timer.timeout.connect(self._refresh_frequency_limits)
        self.frequency_limit_timer.start()

        self.output_state_timer = QTimer(self)
        self.output_state_timer.setInterval(100)
        self.output_state_timer.timeout.connect(self._refresh_output_state)
        self.output_state_timer.start()

    def _set_wave_combo_key(self, key: str):
        idx = self.wave_combo.findData(key)
        if idx >= 0:
            self.wave_combo.setCurrentIndex(idx)

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
        self.golay_widget.hide()
        self.burst_widget.hide()
        self.pulse_widget.hide()
        self.impulse_widget.hide()
        self.tn_widget.hide()
        self.sawtooth_widget.hide()
        self.prbs_widget.hide()

        if key == "noise":
            self.noise_widget.show()
        elif key == "multitone":
            self.multitone_widget.show()
        elif key == "mls":
            self.mls_widget.show()
        elif key == "golay":
            self.golay_widget.show()
        elif key in {"burst", "burst_windowed"}:
            self.burst_widget.show()
        elif key == "pulse":
            self.pulse_widget.show()
        elif key == "impulse":
            self.impulse_widget.show()
        elif key == "tone_noise":
            self.tn_widget.show()
        elif key == "sawtooth":
            self.sawtooth_widget.show()
        elif key == "prbs":
            self.prbs_widget.show()

        use_freq = key not in {"noise", "mls", "golay", "prbs"}
        self.freq_spin.setEnabled(use_freq)
        self.freq_slider.setEnabled(use_freq)

        # Delay UI is only relevant for burst variants (engine applies delay for burst only).
        show_delay = key in {"burst", "burst_windowed"}
        self.delay_label.setVisible(show_delay)
        self.delay_spin.setVisible(show_delay)
        self.delay_slider.setVisible(show_delay)

        if hasattr(self, "fm_group"):
            self._refresh_waveform_compatibility(key)
        if hasattr(self, "left_condition_badge"):
            self._refresh_condition_badges()

    def _refresh_waveform_compatibility(self, waveform_key: str):
        supports_frequency_modulation = waveform_key in self.module.PERIODIC_WAVEFORMS
        unavailable_tip = tr("Unavailable for the selected waveform.")

        for group, param_name in (
            (self.fm_group, "fm_enabled"),
            (self.pm_group, "pm_enabled"),
        ):
            if not supports_frequency_modulation and group.isChecked():
                group.blockSignals(True)
                group.setChecked(False)
                group.blockSignals(False)
                for params in self.get_active_params_list():
                    self.module.update_param(params, param_name, False)
            group.setEnabled(supports_frequency_modulation)
            group.setToolTip("" if supports_frequency_modulation else unavailable_tip)

        filters_available = scipy is not None
        filter_tip = "" if filters_available else tr("Filters require SciPy, which is not available.")
        for group, param_name in (
            (self.lpf_group, "lpf_enabled"),
            (self.hpf_group, "hpf_enabled"),
            (self.notch_group, "notch_enabled"),
        ):
            if not filters_available:
                if group.isChecked():
                    group.blockSignals(True)
                    group.setChecked(False)
                    group.blockSignals(False)
                for params in (self.module.params_L, self.module.params_R):
                    if getattr(params, param_name):
                        self.module.update_param(params, param_name, False)
            group.setEnabled(filters_available)
            group.setToolTip(filter_tip)

        self.wave_combo.setEnabled(not self.sweep_group.isChecked())

    def _current_level_unit(self) -> str:
        return str(self.unit_combo.currentData() or "dBFS")

    def _refresh_calibration_ui(self, force: bool = False):
        calibration = self.module.audio_engine.calibration
        calibrated = bool(getattr(calibration, "output_gain_is_calibrated", False))
        output_gain = float(getattr(calibration, "output_gain", 1.0) or 1.0)
        signature = (calibrated, output_gain)
        if not force and signature == self._last_output_calibration_signature:
            return

        current_unit = self._current_level_unit() if self.unit_combo.count() else "dBFS"
        physical_units = {"dBV", "dBu", "Vrms", "Vpeak"}
        if not calibrated and current_unit in physical_units:
            current_unit = "dBFS"

        self.unit_combo.blockSignals(True)
        self.unit_combo.clear()
        self.unit_combo.addItem(tr("Full Scale (Peak)"), "Linear (0-1)")
        self.unit_combo.addItem("dBFS", "dBFS")
        if calibrated:
            for unit in ("dBV", "dBu", "Vrms", "Vpeak"):
                self.unit_combo.addItem(unit, unit)

        index = self.unit_combo.findData(current_unit)
        if index < 0:
            index = self.unit_combo.findData("dBFS")
        self.unit_combo.setCurrentIndex(index)
        self.unit_combo.blockSignals(False)
        self._last_output_calibration_signature = signature

        params = self.get_active_params_list()
        if params:
            self.update_amp_display_value(params[0].amplitude)
        self._refresh_condition_badges()

    def _format_output_level(self, params: SignalParameters) -> str:
        unit = self._current_level_unit()
        gain = float(getattr(self.module.audio_engine.calibration, "output_gain", 1.0) or 1.0)
        value = linear_to_amplitude(params.amplitude, unit, gain, self._crest_factor_for_params(params))
        if unit == "Linear (0-1)":
            return tr("{0:.3f} FS peak").format(value)
        if unit in {"dBFS", "dBV", "dBu"}:
            return f"{value:.2f} {unit}"
        return f"{value:.3f} {unit}"

    def _crest_factor_for_params(self, params: SignalParameters) -> float:
        waveform = params.waveform
        if waveform in {"square", "pulse", "mls", "golay", "prbs"}:
            return 1.0
        if waveform in {"triangle", "sawtooth"}:
            return float(np.sqrt(3.0))
        return float(np.sqrt(2.0))

    def _format_channel_condition(self, channel: str, params: SignalParameters) -> str:
        routed = self.module.output_mode == "STEREO" or self.module.output_mode == channel
        route_text = tr("Routed") if routed else tr("Not routed")
        waveform_key = "burst_windowed" if params.waveform == "burst" and params.burst_windowed else params.waveform
        waveform_text = self.waveform_labels.get(waveform_key, waveform_key)

        if params.sweep_enabled:
            frequency_text = tr("{0} to {1}").format(
                format_si(params.start_freq, "Hz"),
                format_si(params.end_freq, "Hz"),
            )
        elif params.waveform in {"noise", "mls", "golay", "prbs"}:
            frequency_text = tr("Broadband")
        else:
            frequency_text = format_si(params.frequency, "Hz")

        channel_name = tr("Left") if channel == "L" else tr("Right")
        return (
            f"<b>{channel_name} · {route_text}</b><br>"
            f"{waveform_text} · {frequency_text} · {self._format_output_level(params)}"
        )

    def _refresh_condition_badges(self):
        if not hasattr(self, "left_condition_badge") or not self.unit_combo.count():
            return

        self.left_condition_badge.setText(self._format_channel_condition("L", self.module.params_L))
        self.right_condition_badge.setText(self._format_channel_condition("R", self.module.params_R))

        calibration = self.module.audio_engine.calibration
        calibrated = bool(getattr(calibration, "output_gain_is_calibrated", False))
        if calibrated:
            gain = float(getattr(calibration, "output_gain", 1.0) or 1.0)
            self.calibration_condition_badge.setText(tr("Output calibrated<br>{0:.4g} Vpeak/FS").format(gain))
        else:
            self.calibration_condition_badge.setText(tr("Output uncalibrated<br>Relative units only"))

        dark = self._current_theme_name == "dark"
        active_bg = "#244b36" if dark else "#dff3e6"
        inactive_bg = "#333333" if dark else "#eeeeee"
        border = "#6c8f78" if dark else "#8bb99a"
        muted_border = "#666666" if dark else "#bdbdbd"
        text_color = "#f0f0f0" if dark else "#202020"
        for channel, badge in (("L", self.left_condition_badge), ("R", self.right_condition_badge)):
            routed = self.module.output_mode == "STEREO" or self.module.output_mode == channel
            badge.setStyleSheet(
                f"background: {active_bg if routed else inactive_bg}; color: {text_color}; "
                f"border: 1px solid {border if routed else muted_border}; border-radius: 4px;"
            )
        self.calibration_condition_badge.setStyleSheet(
            f"background: {inactive_bg}; color: {text_color}; border: 1px solid {muted_border}; border-radius: 4px;"
        )

    def _refresh_output_state(self):
        self._refresh_calibration_ui()
        expected_checked = bool(self.module.is_playing)
        if self.toggle_btn.isChecked() != expected_checked:
            self.toggle_btn.blockSignals(True)
            self.toggle_btn.setChecked(expected_checked)
            self.toggle_btn.blockSignals(False)
        self.toggle_btn.setText(tr("Stop Output") if expected_checked else tr("Start Output"))

        overload_channels = [channel for channel in ("L", "R") if self.module.output_overload_latched[channel]]
        if overload_channels:
            channel_text = ", ".join(overload_channels)
            message = tr("OUTPUT OVERLOAD ({0}) — generated signal was limited to 0 dBFS.").format(channel_text)
            self.output_message_label.setText(message)
            self.output_message_label.setStyleSheet(
                "background: #7f1d1d; color: white; border-radius: 4px; padding: 6px; font-weight: bold;"
            )
            self.output_message_label.show()
        elif self._output_error_message:
            self.output_message_label.setText(self._output_error_message)
            self.output_message_label.setStyleSheet(
                "background: #7f1d1d; color: white; border-radius: 4px; padding: 6px; font-weight: bold;"
            )
            self.output_message_label.show()
        else:
            self.output_message_label.hide()
        self._refresh_condition_badges()

    def init_ui(self):
        layout = QVBoxLayout()

        # --- Top Control Bar ---
        layout.addLayout(self._create_top_control_bar())
        layout.addLayout(self._create_output_condition_bar())

        self.output_message_label = QLabel()
        self.output_message_label.setWordWrap(True)
        self.output_message_label.hide()
        layout.addWidget(self.output_message_label)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("signalGeneratorSettingsScroll")
        self.settings_scroll.setProperty("measurelabScrollRole", "outer-controls")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        settings_body = QWidget()
        settings_layout = QVBoxLayout(settings_body)
        settings_layout.setContentsMargins(0, 0, 0, 0)

        # --- Target Selector ---
        settings_layout.addLayout(self._create_target_selector())

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        settings_layout.addWidget(line)

        # --- Main Controls ---
        settings_layout.addWidget(self._create_signal_params_group())

        # --- Advanced Controls ---
        settings_layout.addWidget(self._create_advanced_controls())

        settings_layout.addStretch()
        self.settings_scroll.setWidget(settings_body)
        layout.addWidget(self.settings_scroll, 1)
        self.setLayout(layout)

        # Initialize UI with current target (L)
        self._refresh_frequency_limits(force=True)
        self.load_params_to_ui(self.module.params_L)
        self._refresh_calibration_ui(force=True)
        self._refresh_output_state()

    def _create_top_control_bar(self):
        top_bar = QHBoxLayout()

        # Start/Stop
        self.toggle_btn = QPushButton(tr("Start Output"))
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setMinimumHeight(40)
        self.toggle_btn.clicked.connect(self.on_toggle)
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

    def _create_output_condition_bar(self):
        condition_bar = QHBoxLayout()
        self.left_condition_badge = QLabel()
        self.right_condition_badge = QLabel()
        self.calibration_condition_badge = QLabel()
        for badge in (
            self.left_condition_badge,
            self.right_condition_badge,
            self.calibration_condition_badge,
        ):
            badge.setWordWrap(True)
            badge.setMargin(6)

        condition_bar.addWidget(self.left_condition_badge, 2)
        condition_bar.addWidget(self.right_condition_badge, 2)
        condition_bar.addWidget(self.calibration_condition_badge, 1)
        return condition_bar

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
        basic_controls = QWidget()
        basic_layout = QFormLayout(basic_controls)
        basic_layout.setContentsMargins(0, 0, 0, 0)

        self._init_waveform_selector(basic_layout)
        self._init_param_stack(basic_layout)
        self._init_frequency_controls(basic_layout)
        self._init_amplitude_controls(basic_layout)

        return basic_controls

    def _create_advanced_controls(self):
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)

        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText(tr("Advanced Settings"))
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setProperty("measurelabLayoutAuditExpand", True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        wrapper_layout.addWidget(self.advanced_toggle)

        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        advanced_layout.addWidget(self._create_options_tabs())

        self.advanced_panel.hide()
        self.advanced_toggle.toggled.connect(self._on_advanced_toggled)
        wrapper_layout.addWidget(self.advanced_panel)
        return wrapper

    def _on_advanced_toggled(self, checked: bool):
        self.advanced_panel.setVisible(checked)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    def _init_waveform_selector(self, layout):
        self.wave_combo = QComboBox()
        for key, label in self.waveform_labels.items():
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
        for label, key in (
            (tr("White"), "white"),
            (tr("Pink"), "pink"),
            (tr("Brown"), "brown"),
            (tr("Blue"), "blue"),
            (tr("Violet"), "violet"),
            (tr("Grey"), "grey"),
        ):
            self.noise_combo.addItem(label, key)
        self.noise_combo.currentIndexChanged.connect(
            lambda _index: self.update_param("noise_color", self.noise_combo.currentData())
        )
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

        # 4. Golay Params
        self.golay_widget = QWidget()
        golay_form = QFormLayout(self.golay_widget)
        self.golay_pair_combo = QComboBox()
        self.golay_pair_combo.addItem(tr("A"), "A")
        self.golay_pair_combo.addItem(tr("B"), "B")
        self.golay_pair_combo.currentIndexChanged.connect(
            lambda _i: self.update_param("golay_pair", self.golay_pair_combo.currentData())
        )
        golay_form.addRow(tr("Pair:"), self.golay_pair_combo)

        self.golay_order_combo = QComboBox()
        self.golay_order_combo.addItems([str(i) for i in range(4, 21)])
        self.golay_order_combo.setCurrentText("12")
        self.golay_order_combo.currentTextChanged.connect(lambda v: self.update_param("golay_order", int(v)))
        golay_form.addRow(tr("Order (N):"), self.golay_order_combo)

        # 5. Burst Params
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

        # 6. Pulse Params
        self.pulse_widget = QWidget()
        pulse_form = QFormLayout(self.pulse_widget)
        self.pulse_width_spin = QDoubleSpinBox()
        self.pulse_width_spin.setRange(0.1, 99.9)
        self.pulse_width_spin.setValue(50.0)
        self.pulse_width_spin.setSuffix("%")
        self.pulse_width_spin.valueChanged.connect(lambda v: self.update_param("pulse_width", v))
        pulse_form.addRow(tr("Pulse Width:"), self.pulse_width_spin)

        # 7. Impulse Params
        self.impulse_widget = QWidget()
        impulse_form = QFormLayout(self.impulse_widget)
        self.impulse_samples_spin = QSpinBox()
        self.impulse_samples_spin.setRange(1, 1000000)
        self.impulse_samples_spin.setValue(1)
        self.impulse_samples_spin.valueChanged.connect(lambda v: self.update_param("impulse_samples", v))
        impulse_form.addRow(tr("Impulse Length (samples):"), self.impulse_samples_spin)

        # 8. Tone+Noise Params
        self.tn_widget = QWidget()
        tn_form = QFormLayout(self.tn_widget)
        self.noise_amp_spin = QDoubleSpinBox()
        self.noise_amp_spin.setRange(0.0, 1.0)
        self.noise_amp_spin.setSingleStep(0.01)
        self.noise_amp_spin.setValue(0.1)
        self.noise_amp_spin.valueChanged.connect(lambda v: self.update_param("noise_amplitude", v))
        tn_form.addRow(tr("Noise Amplitude:"), self.noise_amp_spin)

        # 9. Sawtooth Params
        self.sawtooth_widget = QWidget()
        saw_form = QFormLayout(self.sawtooth_widget)
        self.saw_type_combo = QComboBox()
        self.saw_type_combo.addItem(tr("Rising"), "Raising")
        self.saw_type_combo.addItem(tr("Falling"), "Falling")
        self.saw_type_combo.currentIndexChanged.connect(
            lambda _index: self.update_param("sawtooth_type", self.saw_type_combo.currentData())
        )
        saw_form.addRow(tr("Type:"), self.saw_type_combo)

        # 10. PRBS Params
        self.prbs_widget = QWidget()
        prbs_form = QFormLayout(self.prbs_widget)

        self.prbs_order_combo = QComboBox()
        # Common PRBS orders: 7, 9, 11, 15, 20, 23, 31 (31 might be too large for buffer? 2GB buffer.. let's limit to 20 ~1M samples)
        self.prbs_order_combo.addItems([str(i) for i in (7, 9, 10, 11, 15, 17, 20, 23)])
        self.prbs_order_combo.setCurrentText("15")
        self.prbs_order_combo.currentTextChanged.connect(lambda v: self.update_param("prbs_order", int(v)))
        prbs_form.addRow(tr("Order (N):"), self.prbs_order_combo)

        self.prbs_seed_spin = QSpinBox()
        self.prbs_seed_spin.setRange(0, 999999)
        self.prbs_seed_spin.setValue(1)
        self.prbs_seed_spin.valueChanged.connect(lambda v: self.update_param("prbs_seed", v))
        prbs_form.addRow(tr("Seed:"), self.prbs_seed_spin)

        self.param_layout.addWidget(self.noise_widget)
        self.param_layout.addWidget(self.multitone_widget)
        self.param_layout.addWidget(self.mls_widget)
        self.param_layout.addWidget(self.golay_widget)
        self.param_layout.addWidget(self.burst_widget)
        self.param_layout.addWidget(self.pulse_widget)
        self.param_layout.addWidget(self.impulse_widget)
        self.param_layout.addWidget(self.tn_widget)
        self.param_layout.addWidget(self.sawtooth_widget)
        self.param_layout.addWidget(self.prbs_widget)
        self.noise_widget.hide()
        self.multitone_widget.hide()
        self.mls_widget.hide()
        self.golay_widget.hide()
        self.burst_widget.hide()
        self.pulse_widget.hide()
        self.impulse_widget.hide()
        self.tn_widget.hide()
        self.sawtooth_widget.hide()
        self.prbs_widget.hide()

        layout.addRow(self.param_stack)

    def _init_frequency_controls(self, layout):
        freq_layout = QHBoxLayout()
        self.freq_spin = PreferredNumberSpinBox()
        self.freq_spin.setRange(1, self._get_nyquist_frequency())
        self.freq_spin.setDecimals(3)
        self.freq_spin.setGroupSeparatorShown(True)
        self.freq_spin.setValue(1000)
        self.freq_spin.valueChanged.connect(self.on_freq_spin_changed)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(0, 1000)
        self.freq_slider.valueChanged.connect(self.on_freq_slider_changed)

        freq_layout.addWidget(self.freq_spin)
        freq_layout.addWidget(self.freq_slider)
        layout.addRow(tr("Frequency (Hz):"), freq_layout)

    def _get_nyquist_frequency(self) -> float:
        try:
            sample_rate = float(getattr(self.module.audio_engine, "sample_rate", 48000) or 48000)
        except Exception:
            sample_rate = 48000.0
        return max(1.000001, sample_rate / 2.0)

    def _get_filter_frequency_max(self) -> float:
        nyquist_freq = self._get_nyquist_frequency()
        epsilon = max(0.01, nyquist_freq * 1e-9)
        return max(1.0, nyquist_freq - epsilon)

    def _refresh_frequency_limits(self, force: bool = False):
        nyquist_freq = self._get_nyquist_frequency()
        if not force and self._last_nyquist_freq is not None and abs(nyquist_freq - self._last_nyquist_freq) <= 1e-9:
            return

        self._last_nyquist_freq = nyquist_freq

        for spin_name in (
            "freq_spin",
            "start_freq_spin",
            "end_freq_spin",
            "am_freq_spin",
            "fm_freq_spin",
            "pm_freq_spin",
        ):
            spin = getattr(self, spin_name, None)
            if spin is not None:
                spin.setMaximum(nyquist_freq)

        filter_max = self._get_filter_frequency_max()
        for spin_name in ("lpf_freq_spin", "hpf_freq_spin", "notch_freq_spin"):
            spin = getattr(self, spin_name, None)
            if spin is not None:
                spin.setMaximum(filter_max)

        for params in (self.module.params_L, self.module.params_R):
            for name in self.FREQUENCY_PARAM_NAMES:
                value = getattr(params, name, None)
                if value is None:
                    continue
                max_value = filter_max if name in self.FILTER_FREQUENCY_PARAM_NAMES else nyquist_freq
                if value > max_value:
                    self.module.update_param(params, name, max_value)

        params_list = self.get_active_params_list()
        if params_list and hasattr(self, "freq_slider"):
            self.freq_slider.blockSignals(True)
            self.freq_slider.setValue(self._freq_to_slider(params_list[0].frequency))
            self.freq_slider.blockSignals(False)

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
        self.unit_combo.currentIndexChanged.connect(self.on_unit_changed)

        self.amp_slider = QSlider(Qt.Orientation.Horizontal)
        self.amp_slider.setRange(0, 100)
        self.amp_slider.valueChanged.connect(self.on_amp_slider_changed)

        amp_layout.addWidget(self.amp_spin)
        amp_layout.addWidget(self.unit_combo)
        amp_layout.addWidget(self.amp_slider)
        layout.addRow(tr("Output Level:"), amp_layout)

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
        snap_layout.addWidget(QLabel(tr("FFT Size:")))
        snap_layout.addWidget(self.fft_size_combo, 1)  # Stretch

        # We assume the user wants this associated with "Frequency Snap" label or similar?
        # Or just "Bin Snap"
        layout.addRow(tr("Bin Snap:"), snap_layout)

        # Apply Frequency Calibration Checkbox
        cal_layout = QHBoxLayout()
        self.cal_check = QCheckBox(tr("Apply Frequency Calibration"))
        self.cal_check.toggled.connect(self.on_cal_toggled)

        self.cal_ppm_label = QLabel(tr("Fine Tune:"))
        self.cal_ppm_spin = QDoubleSpinBox()
        self.cal_ppm_spin.setRange(-1000.0, 1000.0)
        self.cal_ppm_spin.setSingleStep(0.001)
        self.cal_ppm_spin.setDecimals(3)
        self.cal_ppm_spin.setSuffix(" ppm")
        self.cal_ppm_spin.setToolTip(tr("Manual Frequency Calibration Adjustment"))
        self.cal_ppm_spin.valueChanged.connect(self.on_cal_ppm_changed)

        self.cal_freq_label = QLabel("")
        self.cal_freq_label.setStyleSheet("color: gray;")

        cal_layout.addWidget(self.cal_check)
        cal_layout.addWidget(self.cal_ppm_label)
        cal_layout.addWidget(self.cal_ppm_spin)
        cal_layout.addWidget(self.cal_freq_label)
        cal_layout.addStretch()
        layout.addRow(tr("Frequency Calibration:"), cal_layout)

    def _create_options_tabs(self):
        tabs = QTabWidget()
        self.options_tabs = tabs

        general_page = QWidget()
        general_form = QFormLayout(general_page)
        self._init_phase_controls(general_form)
        self._init_delay_controls(general_form)
        self._init_bin_snap_controls(general_form)
        tabs.addTab(general_page, tr("General"))

        sweep_page = QWidget()
        sweep_layout = QHBoxLayout(sweep_page)
        sweep_layout.setContentsMargins(4, 4, 4, 4)
        sweep_layout.addWidget(self._create_freq_sweep_tab())
        sweep_layout.addWidget(self._create_amp_sweep_tab())
        tabs.addTab(sweep_page, tr("Sweep"))

        modulation_page = QWidget()
        modulation_layout = QHBoxLayout(modulation_page)
        modulation_layout.setContentsMargins(4, 4, 4, 4)
        modulation_layout.addWidget(self._create_am_tab())
        modulation_layout.addWidget(self._create_fm_tab())
        modulation_layout.addWidget(self._create_pm_tab())
        tabs.addTab(modulation_page, tr("Modulation"))

        filter_page = QWidget()
        filter_layout = QHBoxLayout(filter_page)
        filter_layout.setContentsMargins(4, 4, 4, 4)
        filter_layout.addWidget(self._create_lpf_tab())
        filter_layout.addWidget(self._create_hpf_tab())
        filter_layout.addWidget(self._create_notch_tab())
        tabs.addTab(filter_page, tr("Filters"))
        return tabs

    def _create_filter_tab(self, prefix: str, title: str, default_freq: float) -> QWidget:
        filter_widget = QWidget()
        layout = QVBoxLayout(filter_widget)

        group = QGroupBox(title)
        group.setCheckable(True)
        group.setChecked(False)
        # Capture prefix in lambda default arg
        group.toggled.connect(lambda v, p=prefix: self.update_param(f"{p}_enabled", v))
        setattr(self, f"{prefix}_group", group)

        form_layout = QFormLayout()

        freq_spin = PreferredNumberSpinBox()
        freq_spin.setRange(1, self._get_filter_frequency_max())
        freq_spin.setValue(default_freq)
        freq_spin.setGroupSeparatorShown(True)
        freq_spin.valueChanged.connect(lambda v, p=prefix: self.update_param(f"{p}_freq", v))
        form_layout.addRow(tr("Cutoff Freq (Hz):"), freq_spin)
        setattr(self, f"{prefix}_freq_spin", freq_spin)

        order_spin = QSpinBox()
        order_spin.setRange(1, 20)
        order_spin.setValue(4)
        order_spin.valueChanged.connect(lambda v, p=prefix: self.update_param(f"{p}_order", v))
        form_layout.addRow(tr("Order:"), order_spin)
        setattr(self, f"{prefix}_order_spin", order_spin)

        group.setLayout(form_layout)

        layout.addWidget(group)
        layout.addStretch()

        return filter_widget

    def _create_lpf_tab(self):
        return self._create_filter_tab("lpf", tr("Low Pass Filter (LPF)"), 20000.0)

    def _create_hpf_tab(self):
        return self._create_filter_tab("hpf", tr("High Pass Filter (HPF)"), 20.0)

    def _create_notch_tab(self):
        filter_widget = QWidget()
        layout = QVBoxLayout(filter_widget)

        group = QGroupBox(tr("Notch Filter"))
        group.setCheckable(True)
        group.setChecked(False)
        group.toggled.connect(lambda v: self.update_param("notch_enabled", v))
        self.notch_group = group

        form_layout = QFormLayout()

        freq_spin = PreferredNumberSpinBox()
        freq_spin.setRange(1, self._get_filter_frequency_max())
        freq_spin.setValue(1000.0)
        freq_spin.setGroupSeparatorShown(True)
        freq_spin.valueChanged.connect(lambda v: self.update_param("notch_freq", v))
        form_layout.addRow(tr("Frequency (Hz):"), freq_spin)
        self.notch_freq_spin = freq_spin

        q_spin = QDoubleSpinBox()
        q_spin.setRange(0.1, 100.0)
        q_spin.setValue(30.0)
        q_spin.valueChanged.connect(lambda v: self.update_param("notch_q", v))
        form_layout.addRow(tr("Quality Factor (Q):"), q_spin)
        self.notch_q_spin = q_spin

        group.setLayout(form_layout)

        layout.addWidget(group)
        layout.addStretch()

        return filter_widget

    def _create_freq_sweep_tab(self):
        sweep_group = QGroupBox(tr("Frequency Sweep (Sine Only)"))
        sweep_group.setCheckable(True)
        sweep_group.setChecked(False)
        sweep_group.toggled.connect(self.on_sweep_toggled)
        self.sweep_group = sweep_group

        sweep_layout = QFormLayout()

        self.start_freq_spin = PreferredNumberSpinBox()
        self.start_freq_spin.setRange(1, self._get_nyquist_frequency())
        self.start_freq_spin.valueChanged.connect(lambda v: self.update_param("start_freq", v))
        sweep_layout.addRow(tr("Start Freq:"), self.start_freq_spin)

        self.end_freq_spin = PreferredNumberSpinBox()
        self.end_freq_spin.setRange(1, self._get_nyquist_frequency())
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

    def _create_amp_sweep_tab(self):
        amp_sweep_group = QGroupBox(tr("Amplitude Sweep"))
        amp_sweep_group.setCheckable(True)
        amp_sweep_group.setChecked(False)
        amp_sweep_group.toggled.connect(lambda v: self.update_param("amp_sweep_enabled", v))
        self.amp_sweep_group = amp_sweep_group

        amp_sweep_layout = QFormLayout()

        self.start_amp_spin = QDoubleSpinBox()
        self.start_amp_spin.setRange(0.0, 1.0)
        self.start_amp_spin.setSingleStep(0.05)
        self.start_amp_spin.setValue(0.1)
        self.start_amp_spin.valueChanged.connect(self.on_start_amp_changed)
        amp_sweep_layout.addRow(tr("Start Amp:"), self.start_amp_spin)

        self.end_amp_spin = QDoubleSpinBox()
        self.end_amp_spin.setRange(0.0, 1.0)
        self.end_amp_spin.setSingleStep(0.05)
        self.end_amp_spin.setValue(1.0)
        self.end_amp_spin.valueChanged.connect(self.on_end_amp_changed)
        amp_sweep_layout.addRow(tr("End Amp:"), self.end_amp_spin)

        self.amp_duration_spin = QDoubleSpinBox()
        self.amp_duration_spin.setRange(0.1, 60.0)
        self.amp_duration_spin.setValue(5.0)
        self.amp_duration_spin.valueChanged.connect(lambda v: self.update_param("amp_sweep_duration", v))
        amp_sweep_layout.addRow(tr("Duration (s):"), self.amp_duration_spin)

        self.amp_log_check = QCheckBox(tr("Logarithmic Sweep (dB)"))
        self.amp_log_check.toggled.connect(lambda v: self.update_param("log_amp_sweep", v))
        amp_sweep_layout.addRow(self.amp_log_check)

        amp_sweep_group.setLayout(amp_sweep_layout)
        return amp_sweep_group

    def _create_am_tab(self):
        am_group = QGroupBox(tr("AM (Amplitude Modulation)"))
        am_group.setCheckable(True)
        am_group.setChecked(False)
        am_group.toggled.connect(lambda v: self.update_param("am_enabled", v))
        self.am_group = am_group

        am_layout = QFormLayout()

        self.am_freq_spin = PreferredNumberSpinBox()
        self.am_freq_spin.setRange(0.01, self._get_nyquist_frequency())
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
        am_layout.addRow(tr("Depth:"), self.am_depth_spin)

        am_group.setLayout(am_layout)
        return am_group

    def _create_fm_tab(self):
        fm_group = QGroupBox(tr("FM (Frequency Modulation)"))
        fm_group.setCheckable(True)
        fm_group.setChecked(False)
        fm_group.toggled.connect(lambda v: self.update_param("fm_enabled", v))
        self.fm_group = fm_group

        fm_layout = QFormLayout()

        self.fm_freq_spin = PreferredNumberSpinBox()
        self.fm_freq_spin.setRange(0.01, self._get_nyquist_frequency())
        self.fm_freq_spin.setDecimals(3)
        self.fm_freq_spin.setValue(5.0)
        self.fm_freq_spin.valueChanged.connect(lambda v: self.update_param("fm_frequency", v))
        fm_layout.addRow(tr("Mod Freq (Hz):"), self.fm_freq_spin)

        self.fm_dev_spin = PreferredNumberSpinBox()
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

        self.pm_freq_spin = PreferredNumberSpinBox()
        self.pm_freq_spin.setRange(0.01, self._get_nyquist_frequency())
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
        if name in self.FILTER_FREQUENCY_PARAM_NAMES:
            value = min(float(value), self._get_filter_frequency_max())
        elif name in self.FREQUENCY_PARAM_NAMES:
            value = min(float(value), self._get_nyquist_frequency())

        for p in self.get_active_params_list():
            self.module.update_param(p, name, value)
        self._refresh_condition_badges()

    def load_params_to_ui(self, params: SignalParameters):
        self._refresh_frequency_limits()

        if params.sweep_enabled and params.waveform != "sine":
            self.module.update_waveform(params, "sine", self.module.audio_engine.sample_rate)

        # Block signals to prevent feedback loops
        self.block_all_signals(True)

        waveform_key = params.waveform
        if params.waveform == "burst" and bool(getattr(params, "burst_windowed", False)):
            waveform_key = "burst_windowed"
        self._set_wave_combo_key(waveform_key)
        self.noise_combo.setCurrentIndex(self.noise_combo.findData(params.noise_color))
        self.mt_count_spin.setValue(params.multitone_count)
        self.mls_order_combo.setCurrentText(str(params.mls_order))
        self.golay_pair_combo.setCurrentIndex(self.golay_pair_combo.findData(getattr(params, "golay_pair", "A")))
        self.golay_order_combo.setCurrentText(str(getattr(params, "golay_order", 12)))
        self.burst_on_spin.setValue(params.burst_on_cycles)
        self.burst_off_spin.setValue(params.burst_off_cycles)
        self.pulse_width_spin.setValue(params.pulse_width)
        self.impulse_samples_spin.setValue(getattr(params, "impulse_samples", 1))
        self.saw_type_combo.setCurrentIndex(self.saw_type_combo.findData(params.sawtooth_type))
        self.noise_amp_spin.setValue(params.noise_amplitude)
        self.prbs_order_combo.setCurrentText(str(params.prbs_order))
        if hasattr(self, "prbs_seed_spin"):
            self.prbs_seed_spin.setValue(params.prbs_seed)

        self.freq_spin.setValue(params.frequency)
        self.freq_slider.setValue(self._freq_to_slider(params.frequency))

        self.cal_check.setChecked(getattr(params, "use_freq_cal", False))
        self.cal_ppm_label.setEnabled(getattr(params, "use_freq_cal", False))
        self.cal_ppm_spin.setValue(getattr(params, "freq_cal_manual_ppm", 0.0))
        self.cal_ppm_spin.setEnabled(getattr(params, "use_freq_cal", False))
        self.update_cal_freq_label()

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

        self.amp_sweep_group.setChecked(params.amp_sweep_enabled)
        # Note: start_amp_spin and end_amp_spin values are populated during update_amp_display_value()
        self.amp_duration_spin.setValue(params.amp_sweep_duration)
        self.amp_log_check.setChecked(params.log_amp_sweep)

        # Filter params
        self.lpf_group.setChecked(params.lpf_enabled)
        self.lpf_freq_spin.setValue(params.lpf_freq)
        self.lpf_order_spin.setValue(params.lpf_order)

        self.hpf_group.setChecked(params.hpf_enabled)
        self.hpf_freq_spin.setValue(params.hpf_freq)
        self.hpf_order_spin.setValue(params.hpf_order)

        self.notch_group.setChecked(getattr(params, "notch_enabled", False))
        self.notch_freq_spin.setValue(getattr(params, "notch_freq", 1000.0))
        self.notch_q_spin.setValue(getattr(params, "notch_q", 30.0))

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
        self._refresh_waveform_compatibility(waveform_key)
        self._refresh_condition_badges()

    def block_all_signals(self, block):
        widgets = [
            self.wave_combo,
            self.noise_combo,
            self.mt_count_spin,
            self.mls_order_combo,
            self.golay_pair_combo,
            self.golay_order_combo,
            self.burst_on_spin,
            self.burst_off_spin,
            self.pulse_width_spin,
            self.impulse_samples_spin,
            self.saw_type_combo,
            self.noise_amp_spin,
            self.prbs_order_combo,
            self.prbs_seed_spin,
            self.freq_spin,
            self.freq_slider,
            self.cal_check,
            self.cal_ppm_spin,
            self.phase_spin,
            self.phase_slider,
            self.delay_spin,
            self.delay_slider,
            self.amp_spin,
            self.amp_slider,
            self.unit_combo,
            self.sweep_group,
            self.start_freq_spin,
            self.end_freq_spin,
            self.duration_spin,
            self.log_check,
            self.amp_sweep_group,
            self.start_amp_spin,
            self.end_amp_spin,
            self.amp_duration_spin,
            self.amp_log_check,
            self.lpf_group,
            self.lpf_freq_spin,
            self.lpf_order_spin,
            self.hpf_group,
            self.hpf_freq_spin,
            self.hpf_order_spin,
            self.notch_group,
            self.notch_freq_spin,
            self.notch_q_spin,
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
        self._refresh_condition_badges()

    def copy_params(self, src, dst):
        for field in fields(SignalParameters):
            if not field.name.startswith("_"):
                setattr(dst, field.name, getattr(src, field.name))

    def on_route_changed(self, btn):
        if self.route_l.isChecked():
            self.module.output_mode = "L"
        elif self.route_r.isChecked():
            self.module.output_mode = "R"
        elif self.route_stereo.isChecked():
            self.module.output_mode = "STEREO"
        self._refresh_condition_badges()

    def on_cal_toggled(self, checked):
        self.update_param("use_freq_cal", checked)
        self.cal_ppm_label.setEnabled(checked)
        self.cal_ppm_spin.setEnabled(checked)
        self.update_cal_freq_label()

    def on_cal_ppm_changed(self, value):
        self.update_param("freq_cal_manual_ppm", value)
        self.update_cal_freq_label()

    def update_cal_freq_label(self):
        params_list = self.get_active_params_list()
        if not params_list:
            self.cal_freq_label.setText("")
            return

        params = params_list[0]
        if getattr(params, "use_freq_cal", False):
            cal_factor = self.module._get_cal_factor(params)
            calibrated_freq = params.frequency * cal_factor
            self.cal_freq_label.setText(f"({calibrated_freq:.3f} Hz)")
        else:
            self.cal_freq_label.setText("")

    def on_snap_toggled(self, checked):
        self._refresh_frequency_limits()
        self.update_param("bin_center_snap", checked)
        self.fft_size_combo.setEnabled(checked)
        # Re-apply frequency to snap it if enabled
        current_freq = self.freq_spin.value()
        self.on_freq_spin_changed(current_freq)

    def on_fft_size_changed(self, text):
        self._refresh_frequency_limits()
        try:
            val = int(text)
            if val > 0:
                self.update_param("fft_size", val)
                # Re-apply frequency to snap with new size
                current_freq = self.freq_spin.value()
                self.on_freq_spin_changed(current_freq)
        except ValueError:
            logger.warning(f"Invalid FFT size provided: {text}")

    def on_sweep_toggled(self, checked: bool):
        if checked:
            self._set_wave_combo_key("sine")
            for params in self.get_active_params_list():
                self.module.update_waveform(params, "sine", self.module.audio_engine.sample_rate)
        self.update_param("sweep_enabled", checked)
        self.wave_combo.setEnabled(not checked)
        self._refresh_condition_badges()

    def on_wave_changed(self, _index):
        self._refresh_frequency_limits()
        key = self.wave_combo.currentData() or self.wave_combo.currentText()
        self._apply_waveform_key(str(key), update_params=True)

        # Refix RMS if unit is maintaining RMS
        unit = self._current_level_unit()
        if unit in {"Vrms", "dBu", "dBV"}:
            # Value in spinner is the desired RMS.
            # We must update peak amplitude to match this RMS with new crest factor.
            self.on_amp_spin_changed(self.amp_spin.value())

    # --- Frequency Helpers ---
    def _freq_to_slider(self, freq):
        max_freq = self._get_nyquist_frequency()
        freq = float(np.clip(freq, 1.0, max_freq))
        return int(1000 * (np.log10(freq) - np.log10(1)) / (np.log10(max_freq) - np.log10(1)))

    def _slider_to_freq(self, val):
        max_freq = self._get_nyquist_frequency()
        log_freq = np.log10(1) + (val / 1000) * (np.log10(max_freq) - np.log10(1))
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

        # Keep DSP state aligned with the visible spin box range.
        return float(np.clip(snapped_freq, self.freq_spin.minimum(), self.freq_spin.maximum()))

    def on_freq_spin_changed(self, val):
        self._refresh_frequency_limits()
        snapped_val = self._get_snapped_frequency(val)

        self.update_param("frequency", snapped_val)
        self.update_cal_freq_label()

        # Block signals to update UI without recursion
        self.freq_spin.blockSignals(True)
        self.freq_slider.blockSignals(True)

        self.freq_spin.setValue(snapped_val)

        self.freq_slider.setValue(self._freq_to_slider(snapped_val if snapped_val > 0 else 1))

        self.freq_spin.blockSignals(False)
        self.freq_slider.blockSignals(False)

    def on_freq_slider_changed(self, val):
        self._refresh_frequency_limits()
        freq = self._slider_to_freq(val)
        snapped_freq = self._get_snapped_frequency(freq)

        self.update_param("frequency", snapped_freq)
        self.update_cal_freq_label()

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
            self.freq_slider.setValue(self._freq_to_slider(snapped_freq if snapped_freq > 0 else 1))

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
    def on_unit_changed(self, _index):
        # Refresh display with current amplitude in new unit
        # We need to know the current amplitude.
        # Since we might be in LINK mode, we take from L (assuming synced) or just the first active.
        params = self.get_active_params_list()[0]
        self.update_amp_display_value(params.amplitude)
        self._refresh_condition_badges()

    def _set_spin_range_by_unit(self, spin, unit):
        if unit == "Linear (0-1)":
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05 if spin != self.amp_spin else 0.1)
        elif unit == "dBFS":
            spin.setRange(-180.0, 0.0)
            spin.setSingleStep(1.0)
        elif unit == "dBV":
            spin.setRange(-180.0, 20.0)
            spin.setSingleStep(1.0)
        elif unit == "dBu":
            spin.setRange(-180.0, 20.0)
            spin.setSingleStep(1.0)
        elif unit == "Vrms":
            spin.setRange(0.0, 100.0)
            spin.setSingleStep(0.1)
        elif unit == "Vpeak":
            spin.setRange(0.0, 100.0)
            spin.setSingleStep(0.1)

    def update_amp_display_value(self, amp_0_1):
        unit = self._current_level_unit()
        gain = self.module.audio_engine.calibration.output_gain
        cf = self._get_current_crest_factor()

        self.amp_spin.blockSignals(True)
        self._set_spin_range_by_unit(self.amp_spin, unit)
        val = linear_to_amplitude(amp_0_1, unit, gain, cf)
        self.amp_spin.setValue(val)
        self.amp_spin.blockSignals(False)

        self.amp_slider.blockSignals(True)
        self.amp_slider.setValue(int(amp_0_1 * 100))
        self.amp_slider.blockSignals(False)

        if hasattr(self, "start_amp_spin") and hasattr(self, "end_amp_spin"):
            params_list = self.get_active_params_list()
            if params_list:
                params = params_list[0]

                self.start_amp_spin.blockSignals(True)
                self._set_spin_range_by_unit(self.start_amp_spin, unit)
                val_start = linear_to_amplitude(params.start_amp, unit, gain, cf)
                self.start_amp_spin.setValue(val_start)
                self.start_amp_spin.blockSignals(False)

                self.end_amp_spin.blockSignals(True)
                self._set_spin_range_by_unit(self.end_amp_spin, unit)
                val_end = linear_to_amplitude(params.end_amp, unit, gain, cf)
                self.end_amp_spin.setValue(val_end)
                self.end_amp_spin.blockSignals(False)

    def on_amp_spin_changed(self, val):
        unit = self._current_level_unit()
        gain = self.module.audio_engine.calibration.output_gain

        cf = self._get_current_crest_factor()
        amp_0_1 = amplitude_to_linear(val, unit, gain, cf)

        self.update_param("amplitude", amp_0_1)

        self.amp_slider.blockSignals(True)
        self.amp_slider.setValue(int(amp_0_1 * 100))
        self.amp_slider.blockSignals(False)

    def on_amp_slider_changed(self, val):
        amp = val / 100.0
        self.update_param("amplitude", amp)
        self.update_amp_display_value(amp)

    def on_start_amp_changed(self, val):
        unit = self._current_level_unit()
        gain = self.module.audio_engine.calibration.output_gain
        cf = self._get_current_crest_factor()
        amp_0_1 = amplitude_to_linear(val, unit, gain, cf)
        self.update_param("start_amp", amp_0_1)

    def on_end_amp_changed(self, val):
        unit = self._current_level_unit()
        gain = self.module.audio_engine.calibration.output_gain
        cf = self._get_current_crest_factor()
        amp_0_1 = amplitude_to_linear(val, unit, gain, cf)
        self.update_param("end_amp", amp_0_1)

    def on_toggle(self, checked):
        if checked:
            self._output_error_message = ""
            try:
                self.module.start_generation()
            except Exception as exc:
                logger.exception("Failed to start signal generator output")
                self._output_error_message = tr("Unable to start output: {0}").format(str(exc))
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.blockSignals(False)
                self.toggle_btn.setText(tr("Start Output"))
            else:
                self.toggle_btn.setText(tr("Stop Output"))
        else:
            self.module.stop_generation()
            self.toggle_btn.setText(tr("Start Output"))
        self._refresh_output_state()

    def apply_theme(self, theme_name=None):
        if not theme_name and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_current_theme()

        if theme_name == "system" and hasattr(self.app, "theme_manager"):
            theme_name = self.app.theme_manager.get_effective_theme()

        self._current_theme_name = theme_name or "light"

        if theme_name == "dark":
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #555; color: white; border: 1px solid #777; border-radius: 4px; padding: 5px; font-weight: bold; }"
                "QPushButton:checked { background-color: #c62828; color: white; border: 1px solid #777; border-radius: 4px; padding: 5px; font-weight: bold; }"
                "QPushButton:hover { background-color: #666; }"
                "QPushButton:checked:hover { background-color: #d32f2f; }"
            )
        else:
            self.toggle_btn.setStyleSheet(
                "QPushButton { background-color: #e0e0e0; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; font-weight: bold; }"
                "QPushButton:checked { background-color: #ffcccc; color: black; border: 1px solid #ccc; border-radius: 4px; padding: 5px; font-weight: bold; }"
                "QPushButton:hover { background-color: #eeeeee; }"
                "QPushButton:checked:hover { background-color: #ffbbbb; }"
            )
        self._refresh_condition_badges()

    def _get_current_crest_factor(self):
        """Returns the Crest Factor (Peak / RMS) for the current waveform."""
        params = self.get_active_params_list()[0]
        return self._crest_factor_for_params(params)
