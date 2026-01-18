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
    print(f"ITD axis: {bnim.itd_axis}")
    print(f"Pattern: {itd_pattern}")
    print(f"Peak ITD: {peak_itd_ms}")
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
    fs = 48000
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
    
    print(f"Symmetry Max Diff: {max_diff}")
    assert max_diff < 1e-5, f"Asymmetry detected: {max_diff}"
    
    bnim.stop_analysis()
