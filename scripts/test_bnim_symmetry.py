import numpy as np

# Mocking the constants and state from BNIMMeter
class MockBNIM:
    def __init__(self):
        self.fft_size = 2048
        self.sample_rate = 48000
        self.max_itd_ms = 0.8
        self.num_itd_bins = 256
        self.freq_min = 20
        self.freq_max = 5000
        self.gain = 1.0
        self.decay = 0.0 # No decay for single frame test
        
        self.enable_ild = True
        self.ild_strength = 0.6
        self.ild_width_db = 6.0
        self.ild_freq_split_hz = 1500.0
        
        # Init logic
        self.itd_axis = np.linspace(-self.max_itd_ms, self.max_itd_ms, self.num_itd_bins)
        self._itd_axis_norm = (self.itd_axis / max(1e-9, float(self.max_itd_ms))).astype(np.float32)
        
        # Mock FFT freqs
        # We need to match rfftfreq length
        self.freq_indices = np.arange(10, 500) # Arbitrary subset
        self.frequencies = np.linspace(self.freq_min, self.freq_max, len(self.freq_indices))
        
        # Mock Phase Model
        delays_s = (self.itd_axis / 1000.0).astype(np.float32)
        self._phase_diff_model = (-2.0 * np.pi * self.frequencies[:, None] * delays_s[None, :]).astype(np.float32)
        
        self.neural_map = np.zeros((len(self.frequencies), self.num_itd_bins))

    def process(self, L, R):
        # Simplified process logic mimicking BNIMMeter.process_buffer
        
        # Hanning window (assume applied or mock it)
        # FFT (mocked by passing random complex numbers as "fft output" for testing?)
        # Or let's operate on "FFT data" directly to avoid calling actual FFT routines, 
        # since we just want to test value mapping symmetry.
        
        # Let's assume L and R are already FFT complex arrays at the specific frequencies
        fft_L = L
        fft_R = R
        
        mag_L = np.abs(fft_L)
        mag_R = np.abs(fft_R)
        
        eps = 1e-10
        mag_sum = mag_L + mag_R + eps
        
        phase_L = np.angle(fft_L)
        phase_R = np.angle(fft_R)
        
        phase_diff_signal = (phase_L - phase_R)[:, np.newaxis]
        phase_diff_model = self._phase_diff_model
        
        coincidence = 0.5 + 0.5 * np.cos(phase_diff_signal - phase_diff_model)
        
        band_intensity = np.log1p(mag_sum * self.gain).astype(np.float32)
        coincidence = coincidence * band_intensity[:, np.newaxis]
        
        if self.enable_ild:
            ild_db = 20.0 * np.log10((mag_L + eps) / (mag_R + eps))
            ild_db = np.clip(ild_db, -60.0, 60.0)
            
            f = self.frequencies.astype(np.float32)
            split = float(self.ild_freq_split_hz)
            ild_band_weight = np.clip((f - split) / max(1.0, split), 0.0, 1.0)
            
            ild_sign = np.tanh(ild_db / max(1e-6, float(self.ild_width_db))).astype(np.float32)
            itd_norm = self._itd_axis_norm
            
            # THE LOGIC UNDER TEST
            lateral = (1.0 + (self.ild_strength * ild_band_weight)[:, None] * (-itd_norm[None, :]) * ild_sign[:, None])
            # Note: code has .astype(np.float32) which we can skip for python logic check or keep
            
            coincidence *= np.clip(lateral, 0.0, 5.0)
            
        return coincidence

def test_symmetry():
    bnim = MockBNIM()
    
    # Generate random L and R "FFT" data
    # Use fixed seed
    np.random.seed(42)
    n_freqs = len(bnim.frequencies)
    
    # Complex random data
    L_raw = np.random.randn(n_freqs) + 1j * np.random.randn(n_freqs)
    R_raw = np.random.randn(n_freqs) + 1j * np.random.randn(n_freqs)
    
    # Process Normal
    res_normal = bnim.process(L_raw, R_raw)
    
    # Process Swapped (Inputs flipped)
    res_swapped = bnim.process(R_raw, L_raw)
    
    # Expectation: 
    # Since ITD axis is effectively reversed (Left<->Right),
    # res_swapped should be the horizontal flip of res_normal.
    # i.e. res_swapped[freq, itd_idx] == res_normal[freq, 255 - itd_idx]
    
    res_normal_flipped = np.fliplr(res_normal)
    
    diff = np.abs(res_swapped - res_normal_flipped)
    max_diff = np.max(diff)
    
    print(f"Max difference between Swapped(L,R) and Flipped(Normal(L,R)): {max_diff}")
    
    if max_diff < 1e-6:
        print("PASS: Logic is symmetric.")
    else:
        print("FAIL: Logic is NOT symmetric.")
        # Analyze where it fails
        # Check specific point
        idx_f = 0
        idx_t = 0
        val_norm = res_normal[idx_f, 255-idx_t]
        val_swap = res_swapped[idx_f, idx_t]
        print(f"Sample mismatch at f={idx_f}, t={idx_t}:")
        print(f"  Normal[flipped]: {val_norm}")
        print(f"  Swapped:         {val_swap}")

if __name__ == "__main__":
    test_symmetry()
