import numpy as np

from src.gui.widgets.bnim_meter import BNIMMeter


class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
    def register_callback(self, cb):
        return 1
    def unregister_callback(self, cid):
        pass

def test_bnim_processing():
    engine = MockAudioEngine()
    bnim = BNIMMeter(engine)
    bnim.start_analysis()

    # Generate a stereo signal with 0.4ms delay (ITD)
    fs = 48000
    t = np.arange(bnim.fft_size) / fs
    freq_test = 1000.0

    L = np.sin(2 * np.pi * freq_test * t)
    # Delay by 0.4ms
    R = np.sin(2 * np.pi * freq_test * (t - 0.0004))

    # Fill buffer
    bnim.audio_buffer = np.zeros((bnim.fft_size, 2))
    bnim.audio_buffer[:, 0] = L
    bnim.audio_buffer[:, 1] = R

    # Process
    bnim.process_buffer()

    # Check neural map
    neural_map = bnim.neural_map
    assert neural_map is not None

    # Find peak
    freq_idx = np.argmin(np.abs(bnim.frequencies - 1000.0))
    itd_pattern = neural_map[freq_idx]

    peak_itd_idx = np.argmax(itd_pattern)
    peak_itd_ms = bnim.itd_axis[peak_itd_idx]

    # Alignment (peak) occurs when tau = -delay
    assert abs(peak_itd_ms - (-0.4)) < 0.05

    bnim.stop_analysis()

def test_bnim_mono():
    engine = MockAudioEngine()
    bnim = BNIMMeter(engine)
    bnim.start_analysis()

    # Mono signal (L=R)
    fs = 48000
    t = np.arange(bnim.fft_size) / fs
    L = np.sin(2 * np.pi * 1000.0 * t)
    R = L

    bnim.audio_buffer = np.zeros((bnim.fft_size, 2))
    bnim.audio_buffer[:, 0] = L
    bnim.audio_buffer[:, 1] = R

    bnim.process_buffer()

    freq_idx = np.argmin(np.abs(bnim.frequencies - 1000.0))
    itd_pattern = bnim.neural_map[freq_idx]
    peak_itd_ms = bnim.itd_axis[np.argmax(itd_pattern)]

    # Peak should be at 0ms
    assert abs(peak_itd_ms) < 0.1 # Relaxed slightly for resolution

    bnim.stop_analysis()

def test_bnim_symmetry():
    engine = MockAudioEngine()
    bnim = BNIMMeter(engine)
    bnim.start_analysis()

    # Enable ILD for this test
    bnim.enable_ild = True
    bnim.ild_strength = 0.6
    bnim.decay = 0.0 # Instant update

    # Generate random stereo noise
    np.random.seed(42)
    noise_L = np.random.randn(bnim.fft_size).astype(np.float32)
    noise_R = np.random.randn(bnim.fft_size).astype(np.float32) * 0.5 # Make R quieter to have ILD

    # Pass 1: Normal (L, R)
    with bnim._buffer_lock:
        bnim.audio_buffer[-bnim.fft_size:, 0] = noise_L
        bnim.audio_buffer[-bnim.fft_size:, 1] = noise_R
        bnim._buffer_seq += 1 # Force update

    bnim.process_buffer()
    map_normal = bnim.neural_map.copy()

    # Pass 2: Swapped (R, L)
    with bnim._buffer_lock:
        bnim.audio_buffer[-bnim.fft_size:, 0] = noise_R
        bnim.audio_buffer[-bnim.fft_size:, 1] = noise_L
        bnim._buffer_seq += 1

    bnim.process_buffer()
    map_swapped = bnim.neural_map.copy()

    # Expectation: map_swapped should be horizontal flip of map_normal
    # neural_map shape: (freqs, itd)
    # flip along axis 1 (itd)
    map_normal_flipped = np.fliplr(map_normal)

    diff = np.abs(map_swapped - map_normal_flipped)
    max_diff = np.max(diff)

    assert max_diff < 1e-5, f"Asymmetry detected: {max_diff}"

    bnim.stop_analysis()

def test_bnim_ild_balance():
    """Test that ILD weighting shifts energy balance (extracted from test_bnim_meter_logic.py)."""
    engine = MockAudioEngine()
    bnim = BNIMMeter(engine)
    bnim.start_analysis()
    bnim.enable_ild = True
    bnim.ild_strength = 1.0 # Strong ILD effect
    bnim.decay = 0.0

    # Create signal where L is much louder than R
    # ILD is positive (L > R).
    np.random.seed(123)
    noise = np.random.normal(0, 0.1, bnim.fft_size).astype(np.float32)
    L_data = noise * 10.0
    R_data = noise * 0.1

    with bnim._buffer_lock:
        bnim.audio_buffer[-bnim.fft_size:, 0] = L_data
        bnim.audio_buffer[-bnim.fft_size:, 1] = R_data
        bnim._buffer_seq += 1

    bnim.process_buffer()

    # Check energy balance
    mid_idx = bnim.num_itd_bins // 2
    left_energy = np.sum(bnim.neural_map[:, :mid_idx])
    right_energy = np.sum(bnim.neural_map[:, mid_idx:])

    # Expect Left Energy > Right Energy
    assert left_energy > right_energy, \
        f"Expected Left Energy > Right Energy for L > R signal. L={left_energy}, R={right_energy}"

    bnim.stop_analysis()
