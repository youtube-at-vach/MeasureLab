from unittest.mock import MagicMock
import numpy as np
import pytest
from scipy import signal

# Now import the module - since we are in CI environment with PyQt6 installed,
# or in a local env where we might want to mock it if missing.
# However, modifying sys.modules globally is dangerous for other tests.
# If we are in a headless environment, standard PyQt6 imports should work if installed.
from src.gui.widgets.lufs_meter import LufsMeter


class MockAudioEngine:
    def __init__(self, sample_rate=48000):
        self.sample_rate = sample_rate
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = 0.0
        self._callback = None

    def register_callback(self, callback):
        self._callback = callback
        return 1

    def unregister_callback(self, callback_id):
        self._callback = None


@pytest.fixture
def lufs_meter():
    engine = MockAudioEngine()
    meter = LufsMeter(engine)
    return meter


def generate_sine_wave(freq, peak_dbfs, duration, sr):
    """Generate stereo sine wave at given dBFS peak level."""
    t = np.linspace(0, duration, int(duration * sr), endpoint=False)
    # peak_dbfs = 20 * log10(peak_amp) -> peak_amp = 10^(peak_dbfs/20)
    peak_amp = 10 ** (peak_dbfs / 20.0)
    sig = peak_amp * np.sin(2 * np.pi * freq * t)
    # Stereo
    return np.column_stack((sig, sig))


def test_initialization_and_filters(lufs_meter):
    """Verify filter initialization and coefficients."""
    lufs_meter.start_meter()

    # Check if filters are initialized
    assert lufs_meter.b0_shelf is not None
    assert lufs_meter.a0_shelf is not None
    assert lufs_meter.b1_hp is not None
    assert lufs_meter.a1_hp is not None

    # Verify K-weighting response at 1kHz
    # The filter chain is Shelf -> HighPass.
    # BS.1770-4 specifies that the filter response at 1kHz is approx 0.0 dB relative to the input?
    # No, it says "The constant -0.691 dB is included ... filter ... has a gain of 0.691 dB at 1 kHz".
    # So the combined filter gain should be +0.691 dB at 1 kHz.

    w, h_shelf = signal.freqz(lufs_meter.b0_shelf, lufs_meter.a0_shelf, worN=[1000], fs=lufs_meter.sample_rate)
    _, h_hp = signal.freqz(lufs_meter.b1_hp, lufs_meter.a1_hp, worN=[1000], fs=lufs_meter.sample_rate)

    gain_linear = np.abs(h_shelf[0] * h_hp[0])
    gain_db = 20 * np.log10(gain_linear)

    assert abs(gain_db - 0.691) < 0.1, f"K-weighting gain at 1kHz expected ~0.691 dB, got {gain_db:.3f} dB"


@pytest.mark.parametrize("sample_rate", [44100, 48000, 96000, 192000])
def test_k_weighting_keeps_reference_response_across_sample_rates(sample_rate):
    """A non-48 kHz device must not shift the fixed 48 kHz weighting curve."""
    meter = LufsMeter(MockAudioEngine(sample_rate))
    meter.start_meter()

    _, shelf = signal.freqz(meter.b0_shelf, meter.a0_shelf, worN=[997], fs=sample_rate)
    _, high_pass = signal.freqz(meter.b1_hp, meter.a1_hp, worN=[997], fs=sample_rate)
    gain_db = 20 * np.log10(abs(shelf[0] * high_pass[0]))

    assert gain_db == pytest.approx(0.691, abs=0.03)


def test_silent_start_does_not_inject_phantom_loudness(lufs_meter):
    """Filter initial conditions must represent no pre-run signal history."""
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    frames = int(0.5 * lufs_meter.sample_rate)

    for start in range(0, frames, 1024):
        block = np.zeros((min(1024, frames - start), 2), dtype=np.float32)
        callback(block, None, len(block), None, None)
    lufs_meter.update_integrated_lufs_if_dirty()

    assert lufs_meter.momentary_lufs == -100.0
    assert lufs_meter.short_term_lufs == -100.0
    assert lufs_meter.integrated_lufs == -100.0
    assert lufs_meter._i_block_ms == []


def test_integrated_gating_is_invariant_to_audio_block_boundaries():
    """The same samples must produce the same 400 ms/75%-overlap blocks."""
    sample_rate = 48000
    sample_count = int(0.8 * sample_rate)
    time_axis = np.arange(sample_count) / sample_rate
    amplitude = np.where(time_axis < 0.2, 0.01, np.where(time_axis < 0.5, 0.5, 0.08))
    mono = (amplitude * np.sin(2 * np.pi * 997 * time_axis)).astype(np.float32)
    stereo = np.column_stack((mono, mono))

    results = []
    for chunk_size in (1024, sample_count):
        meter = LufsMeter(MockAudioEngine(sample_rate))
        meter.start_meter()
        callback = meter.audio_engine._callback
        for start in range(0, sample_count, chunk_size):
            block = stereo[start : start + chunk_size]
            callback(block, None, len(block), None, None)
        meter.update_integrated_lufs_if_dirty()
        results.append((np.asarray(meter._i_block_ms), meter.integrated_lufs))

    expected_block_count = 1 + int((0.8 - 0.4) / 0.1)
    assert len(results[0][0]) == expected_block_count
    np.testing.assert_allclose(results[0][0], results[1][0], rtol=0.0, atol=1e-12)
    assert results[0][1] == pytest.approx(results[1][1], abs=1e-12)


def test_reset_discards_pre_reset_power_from_first_gating_block(lufs_meter):
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    sample_rate = int(lufs_meter.sample_rate)
    loud = generate_sine_wave(997, -6.0, 0.3, sample_rate).astype(np.float32)

    callback(loud, None, len(loud), None, None)
    lufs_meter.reset_integration()

    assert lufs_meter.get_integrated_seconds() == 0.0
    assert lufs_meter._i_block_ms == []
    assert lufs_meter._p_filled_m == 0
    assert lufs_meter._p_filled_s == 0
    assert lufs_meter._p_sum_m == 0.0
    assert lufs_meter._p_sum_s == 0.0
    assert not np.any(lufs_meter._p_ring_m)
    assert not np.any(lufs_meter._p_ring_s)


def test_input_discontinuity_and_sample_rate_change_invalidate_run(lufs_meter):
    class InputOverflow:
        input_overflow = True
        input_underflow = False
        output_overflow = False
        output_underflow = False

        def __bool__(self):
            return True

    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    block = np.zeros((1024, 2), dtype=np.float32)

    callback(block, None, len(block), None, InputOverflow())
    assert not lufs_meter.measurement_valid
    assert lufs_meter.data_gap_detected

    lufs_meter.stop_meter()
    lufs_meter.start_meter()
    lufs_meter.audio_engine.sample_rate = 96000
    callback = lufs_meter.audio_engine._callback
    callback(block, None, len(block), None, None)

    assert not lufs_meter.measurement_valid
    assert lufs_meter.configuration_changed_detected


def test_lufs_calculation_basic(lufs_meter):
    """Test _to_lufs conversion logic."""
    # Test silence
    assert lufs_meter._to_lufs(0.0) == -100.0
    assert lufs_meter._to_lufs(1e-11) == -100.0

    # Test known value: Mean Square 1.0 -> -0.691 LUFS
    # 10 * log10(1.0) = 0.0 -> -0.691
    assert abs(lufs_meter._to_lufs(1.0) - (-0.691)) < 1e-6

    # Test known value: Mean Square 0.1 (-10 dB power) -> -10.691 LUFS
    # 10 * log10(0.1) = -10.0 -> -10.691
    assert abs(lufs_meter._to_lufs(0.1) - (-10.691)) < 1e-6


def test_momentary_lufs_accuracy(lufs_meter):
    """Verify momentary LUFS with a steady 1kHz sine wave."""
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    assert callback is not None

    sr = lufs_meter.sample_rate

    # Target -23.0 LUFS
    # For a stereo sine wave (coherent), Peak dBFS approx equals LUFS reading
    # (RMS is -3dB, Stereo sums to +3dB).
    target_lufs = -23.0
    peak_db = target_lufs

    # Run for 1.0 second
    duration = 1.0
    indata = generate_sine_wave(1000, peak_db, duration, sr)

    chunk_size = 1024
    frames = len(indata)
    for i in range(0, frames, chunk_size):
        chunk = indata[i : i + chunk_size]
        callback(chunk, None, len(chunk), None, None)

    # Check momentary LUFS
    assert abs(lufs_meter.momentary_lufs - target_lufs) < 0.2, (
        f"Expected {target_lufs} LUFS, got {lufs_meter.momentary_lufs}"
    )


def test_integration_and_gating(lufs_meter):
    """Verify integrated loudness calculation with gating."""
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    sr = lufs_meter.sample_rate
    chunk_size = 1024

    # 1. Feed 1 second of -23 LUFS signal
    target_lufs = -23.0
    peak_db = target_lufs
    indata_signal = generate_sine_wave(1000, peak_db, 1.0, sr)

    for i in range(0, len(indata_signal), chunk_size):
        chunk = indata_signal[i : i + chunk_size]
        callback(chunk, None, len(chunk), None, None)

    lufs_meter.update_integrated_lufs_if_dirty()
    # Tolerance 0.5 dB to account for filter transient/warmup in the first few blocks
    assert abs(lufs_meter.integrated_lufs - target_lufs) < 0.5

    # 2. Feed 1 second of silence (-100 LUFS)
    indata_silence = np.zeros((int(1.0 * sr), 2), dtype=np.float32)

    for i in range(0, len(indata_silence), chunk_size):
        chunk = indata_silence[i : i + chunk_size]
        callback(chunk, None, len(chunk), None, None)

    lufs_meter.update_integrated_lufs_if_dirty()

    # Fully silent blocks are gated out. Three standards-defined transition
    # blocks still contain part of the preceding tone and remain above gate.
    assert lufs_meter.integrated_lufs == pytest.approx(-23.70, abs=0.15)

    # 3. Feed 1 second of -20 LUFS (Louder)
    target_lufs_2 = -20.0
    peak_db_2 = target_lufs_2
    indata_signal_2 = generate_sine_wave(1000, peak_db_2, 1.0, sr)

    for i in range(0, len(indata_signal_2), chunk_size):
        chunk = indata_signal_2[i : i + chunk_size]
        callback(chunk, None, len(chunk), None, None)

    lufs_meter.update_integrated_lufs_if_dirty()

    # Expected integrated: Average of 1s at -23 LUFS and 1s at -20 LUFS
    # Note: Transition blocks (signal <-> silence) are included if > gate,
    # pulling the average down slightly.
    expected_lufs_simplified = 10 * np.log10((10 ** (-23 / 10) + 10 ** (-20 / 10)) / 2)

    # Tolerance increased to 1.0 dB to account for transition blocks
    assert abs(lufs_meter.integrated_lufs - expected_lufs_simplified) < 1.0


def test_reset_logic(lufs_meter):
    """Verify reset functionality."""
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    sr = lufs_meter.sample_rate

    indata = generate_sine_wave(1000, -20, 0.5, sr)
    callback(indata, None, len(indata), None, None)
    lufs_meter.update_integrated_lufs_if_dirty()

    assert lufs_meter.integrated_lufs > -90.0
    assert lufs_meter.get_integrated_seconds() > 0.0

    lufs_meter.reset_integration()

    assert lufs_meter.integrated_lufs == -100.0
    assert lufs_meter.get_integrated_seconds() == 0.0

    callback(indata, None, len(indata), None, None)
    lufs_meter.update_integrated_lufs_if_dirty()
    assert lufs_meter.integrated_lufs > -90.0


def test_get_integrated_seconds(lufs_meter):
    """Verify duration tracking."""
    lufs_meter.start_meter()
    callback = lufs_meter.audio_engine._callback
    sr = lufs_meter.sample_rate

    # Feed 1.5 seconds of audio in chunks
    total_frames = int(1.5 * sr)
    chunk_size = 1024

    remaining = total_frames
    while remaining > 0:
        n = min(remaining, chunk_size)
        chunk = np.zeros((n, 2), dtype=np.float32)
        callback(chunk, None, n, None, None)
        remaining -= n

    assert abs(lufs_meter.get_integrated_seconds() - 1.5) < 1e-3
