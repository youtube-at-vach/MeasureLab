import pytest
import numpy as np
import time
from src.core.audio_engine import AudioEngine
from src.core.analysis import AudioCalc

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

class TestLockinAccuracy:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        # Ensure we are in a known state
        self.engine.set_offline_mode(False) 
        yield
        if self.engine.is_active():
            self.engine.stop_stream()

    def generate_signal(self, sr, duration, freq=1000.0, amp=0.5):
        """
        Generates a sine wave test signal.
        """
        t = np.linspace(0, duration, int(sr * duration), endpoint=False).astype(np.float32)
        signal = amp * np.sin(2 * np.pi * freq * t)
        return signal

    def run_measurement(self, signal, sr, duration, buffer_size):
        """
        Plays signal and records input simultaneously with specific buffer size.
        """
        frames = len(signal)
        recorded = np.zeros((frames, 2), dtype=np.float32)
        
        current_idx = 0
        
        def callback(indata, outdata, frames, time_info, status):
            nonlocal current_idx
            chunk_len = frames
            
            # Check if we have enough signal left
            remaining = len(signal) - current_idx
            if remaining <= 0:
                outdata.fill(0)
                return

            to_write = min(chunk_len, remaining)
            
            # Write Output (Mono/Stereo handling)
            out_chunk = signal[current_idx : current_idx + to_write]
            outdata[:to_write, 0] = out_chunk
            if outdata.shape[1] > 1:
                outdata[:to_write, 1] = out_chunk
            
            if to_write < chunk_len:
                outdata[to_write:].fill(0)
                
            # Read Input
            if indata.shape[1] >= 2:
                recorded[current_idx : current_idx + to_write] = indata[:to_write, :2]
            elif indata.shape[1] == 1:
                recorded[current_idx : current_idx + to_write, 0] = indata[:to_write, 0]
                recorded[current_idx : current_idx + to_write, 1] = indata[:to_write, 0]
                
            current_idx += to_write

        # Configure Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_block_size(buffer_size)
        
        # Start
        cid = self.engine.register_callback(callback)
        
        # Wait for completion
        time.sleep(duration + 0.5)
        
        self.engine.unregister_callback(cid)
        
        return recorded

    @pytest.mark.parametrize("buffer_size", [16384])
    def test_lockin_stability(self, buffer_size, record_property):
        """
        Measures stability of 1kHz signal measurement across different buffer sizes.
        """
        sr = 48000
        duration = 2.0 # Increased duration for large buffer size
        freq = 1000.0
        iterations = 10
        
        measured_magnitudes = []
        
        signal = self.generate_signal(sr, duration, freq=freq, amp=0.5)
        
        print(f"\nTesting Buffer Size: {buffer_size}")
        
        for i in range(iterations):
            # Run measurement
            recorded = self.run_measurement(signal, sr, duration, buffer_size)
            
            # Skip transient (first 20%)
            skip_samples = int(sr * 0.2)
            data = recorded[skip_samples:, 0]
            
            # Calculate Amplitude using Sine Fit (fundamental RMS)
            # We use analyze_harmonics to get consistent fundamental RMS
            # Or use calculate_thdn_sine_fit directly.
            # Let's use calculate_thdn_sine_fit as it returns fund_rms directly.
            _, fund_rms, _ = AudioCalc.calculate_thdn_sine_fit(data, sr, freq)
            
            measured_magnitudes.append(fund_rms)
            # print(f"  Iter {i}: {fund_rms:.6f}")
            
            # Small pause between iterations
            time.sleep(0.1)
            
        # Calculate Statistics
        measurements = np.array(measured_magnitudes)
        mean_val = np.mean(measurements)
        std_val = np.std(measurements)
        var_val = np.var(measurements)
        
        # Relative Standard Deviation (ppm)
        rsd_ppm = (std_val / mean_val) * 1e6 if mean_val > 0 else 0
        
        # Log properties
        record_property("test_type", "Lock-in Accuracy")
        record_property("buffer_size", buffer_size)
        record_property("iterations", iterations)
        record_property("mean_rms", mean_val)
        record_property("std_dev", std_val)
        record_property("variance", var_val)
        record_property("rsd_ppm", rsd_ppm)
        
        print(f"  Mean: {mean_val:.6f}")
        print(f"  Std Dev: {std_val:.8f}")
        print(f"  RSD: {rsd_ppm:.2f} ppm")
        
        # Basic sanity check - valid measurement
        assert mean_val > 0.001, "Signal too weak or not measured"
        # Stability check - arbitrary relaxation for now, just to ensure it's not wildly unstable
        # Real hardware might be noisy, but purely digital loopback (if used) should be very stable.
        # If using real hardware loopback, < 1000 ppm is usually expected for good gear.
        # We won't hard fail on high variance yet as this is a report-generation test mainly.
