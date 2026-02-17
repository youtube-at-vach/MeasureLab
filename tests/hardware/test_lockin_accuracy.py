import pytest
import numpy as np
import time
from src.core.audio_engine import AudioEngine
from src.gui.widgets.lock_in_amplifier import LockInAmplifier

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

class TestLockinAccuracy:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        # Ensure we are in a known state
        self.engine.set_offline_mode(False)
        self.lockin = LockInAmplifier(self.engine)
        yield
        if self.lockin.is_running:
            self.lockin.stop_analysis()
        if self.engine.is_active():
            self.engine.stop_stream()

    @pytest.mark.parametrize("buffer_size", [4096, 16384, 65536, 131072])
    def test_lockin_stability(self, buffer_size, record_property):
        """
        Measures stability of 1kHz signal measurement across different buffer sizes
        using the actual LockInAmplifier widget logic.
        """
        sr = 192000
        # For larger buffer sizes, we need longer wait times to ensure buffer fills
        freq = 1000.0
        iterations = 30
        
        # Configure Audio Engine
        self.engine.set_sample_rate(sr)
        
        # Configure Lock-in Amplifier
        self.lockin.gen_frequency = freq
        self.lockin.gen_amplitude = 0.5
        self.lockin.set_buffer_size(buffer_size)
        
        # Configure Routing for Loopback Test
        # signal_channel: 0 (Left), ref_channel: 0 (Left)
        # We use the signal channel as reference too, so it works even with single-channel loopback
        self.lockin.signal_channel = 0
        self.lockin.ref_channel = 0
        
        # Output on Left Channel (0)
        self.lockin.output_channel = 0
        
        # Disable post-processing for raw stability test
        self.lockin.averaging_count = 1
        self.lockin.postmix_lpf_order = 0
        
        # Start Analysis (Hardware + Logic)
        self.lockin.start_analysis()
        
        # Wait for initial settling (at least 2 buffer periods)
        buffer_duration = buffer_size / sr
        initial_wait = max(0.5, buffer_duration * 3.0)
        time.sleep(initial_wait)
        
        measured_magnitudes = []
        
        print(f"\nTesting Buffer Size: {buffer_size}")
        
        for i in range(iterations):
            # Wait for next buffer update (plus margin)
            # The lockin logic processes the *current* buffer in the ring.
            # We want to sample over time.
            time.sleep(max(0.05, buffer_duration * 1.1))
            
            # Execute Logic (usually called by timer)
            self.lockin.process_data()
            
            mag = self.lockin.current_magnitude
            measured_magnitudes.append(mag)
            
            # print(f"  Iter {i}: {mag:.6f}")
            
        # Calculate Statistics
        measurements = np.array(measured_magnitudes)
        # Filter out zeros if any (startup transients)
        measurements = measurements[measurements > 1e-6]
        
        if len(measurements) == 0:
            pytest.fail("No valid measurements obtained")
            
        mean_val = np.mean(measurements)
        std_val = np.std(measurements)
        var_val = np.var(measurements)
        
        # Relative Standard Deviation (ppm)
        rsd_ppm = (std_val / mean_val) * 1e6 if mean_val > 0 else 0
        
        # Log properties
        record_property("test_type", "Lock-in Accuracy (Widget Logic)")
        record_property("buffer_size", buffer_size)
        record_property("iterations", iterations)
        record_property("mean_rms", mean_val)
        record_property("std_dev", std_val)
        record_property("variance", var_val)
        record_property("rsd_ppm", rsd_ppm)
        
        print(f"  Mean: {mean_val:.6f}")
        print(f"  Std Dev: {std_val:.8f}")
        print(f"  RSD: {rsd_ppm:.2f} ppm")
        
        # Basic sanity check
        assert mean_val > 0.001, "Signal too weak or not measured"
        
        # With real hardware logic, stability should be decent.
        # Check against reasonable threshold for loopback
        # assert rsd_ppm < 1000.0, f"Instability too high: {rsd_ppm:.2f} ppm"
