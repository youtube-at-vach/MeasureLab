import json
import time
import pytest
import numpy as np
from pathlib import Path
from src.core.audio_engine import AudioEngine
from src.core.analysis import AudioCalc

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

class TestAudioHardwareMetrics:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        # Ensure we are in a known state
        self.engine.set_offline_mode(False) 
        yield
        if self.engine.is_active():
            self.engine.stop_stream()

    def generate_signal(self, sr, duration, signal_type="sine", freq=1000.0, amp=0.5, freq2=None):
        """
        Generates a test signal.
        """
        t = np.linspace(0, duration, int(sr * duration), endpoint=False).astype(np.float32)
        
        if signal_type == "sine":
            signal = amp * np.sin(2 * np.pi * freq * t)
        elif signal_type == "smpte":
            # SMPTE IMD: 60Hz + 7kHz, 4:1 ratio
            # Low freq (f1) at 60Hz, High freq (f2) at 7kHz
            f1 = 60.0
            f2 = 7000.0
            if freq is not None: f1 = freq
            if freq2 is not None: f2 = freq2
            
            # Amplitude ratio 4:1 means low is 4x high.
            # Total amp normalized to 'amp'
            # A_low + A_high = amp, A_low = 4 * A_high => 5 * A_high = amp
            a_high = amp / 5.0
            a_low = 4.0 * a_high
            
            signal = a_low * np.sin(2 * np.pi * f1 * t) + a_high * np.sin(2 * np.pi * f2 * t)
        elif signal_type == "silence":
            signal = np.zeros_like(t)
        else:
            raise ValueError(f"Unknown signal type: {signal_type}")
            
        return signal

    def run_measurement(self, signal, sr, duration):
        """
        Plays signal and records input simultaneously.
        """
        frames = len(signal)
        recorded = np.zeros((frames, 2), dtype=np.float32)
        
        # We need a proper synchronized play/record.
        # For this test, we accept some latency/misalignment since we just want stable metrics.
        # We'll use a callback that writes output and reads input.
        
        current_idx = 0
        
        def callback(indata, outdata, frames, time_info, status):
            nonlocal current_idx
            chunk_len = frames
            
            # Check if we have enough signal left
            remaining = len(signal) - current_idx
            if remaining <= 0:
                outdata.fill(0)
                # Still record?
                return

            to_write = min(chunk_len, remaining)
            
            # Write Output (Mono/Stereo handling)
            # Assuming signal is mono, map to all output channels
            out_chunk = signal[current_idx : current_idx + to_write]
            outdata[:to_write, 0] = out_chunk
            if outdata.shape[1] > 1:
                outdata[:to_write, 1] = out_chunk
            
            if to_write < chunk_len:
                outdata[to_write:].fill(0)
                
            # Read Input
            # Store stereo input
            if indata.shape[1] >= 2:
                recorded[current_idx : current_idx + to_write] = indata[:to_write, :2]
            elif indata.shape[1] == 1:
                recorded[current_idx : current_idx + to_write, 0] = indata[:to_write, 0]
                recorded[current_idx : current_idx + to_write, 1] = indata[:to_write, 0]
                
            current_idx += to_write

        # Configure Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_block_size(1024)
        
        # Start
        cid = self.engine.register_callback(callback)
        
        # Wait for completion
        # Add buffer for buffer drift/latency
        time.sleep(duration + 0.5)
        
        self.engine.unregister_callback(cid)
        
        # Trim leading silence / latency if needed? 
        # AudioCalc analysis usually handles some drift, but let's just return raw for now.
        return recorded


    def test_thdn_1khz(self, record_property):
        """
        Quick THD+N check at 1kHz.
        """
        sr = 48000
        duration = 1.0 # seconds
        freq = 1000.0
        
        # Generate Signal
        signal = self.generate_signal(sr, duration, "sine", freq=freq, amp=0.5)
        
        # Measure
        recorded = self.run_measurement(signal, sr, duration)
        
        # Analyze Channel 0 (Left)
        # Skip first 200ms to settle
        skip_samples = int(sr * 0.2)
        data = recorded[skip_samples:, 0]
        
        # Calculate THD+N
        # We reuse AudioCalc.analyze_harmonics which gives us everything
        # But we need basic THD+N
        
        metrics = AudioCalc.analyze_harmonics(data, freq, "hann", sr)
        
        thdn_db = metrics["thdn_db"]
        thdn_percent = metrics["thdn_percent"]
        sinad = metrics["sinad_db"]
        
        # Log properties for JSON report
        record_property("test_type", "THD+N")
        record_property("frequency_hz", freq)
        record_property("thdn_db", thdn_db)
        record_property("thdn_percent", thdn_percent)
        record_property("sinad_db", sinad)
        record_property("signal_rms", metrics["raw_fund_rms"])
        record_property("noise_rms", metrics["raw_res_rms"])
        
        # Thresholds (Configurable? For now flexible pass)
        assert thdn_db < -10.0, f"THD+N too high: {thdn_db:.2f} dB (Validation check)"



    def test_imd_smpte(self, record_property):
        """
        SMPTE IMD Measurement (60Hz / 7kHz, 4:1).
        """
        sr = 48000
        duration = 2.0
        
        signal = self.generate_signal(sr, duration, "smpte", amp=0.5)
        recorded = self.run_measurement(signal, sr, duration)
        
        skip_samples = int(sr * 0.2)
        data = recorded[skip_samples:, 0]
        
        # For IMD analysis, we need spectrum
        window = np.hamming(len(data))
        fft_res = np.fft.rfft(data * window)
        freqs = np.fft.rfftfreq(len(data), 1/sr)
        mag = np.abs(fft_res)
        
        # Calculate IMD SMPTE
        imd_res = AudioCalc.calculate_imd_smpte(mag, freqs, 60.0, 7000.0)
        
        record_property("test_type", "IMD SMPTE")
        record_property("imd_smpte_db", imd_res["imd_db"])
        record_property("imd_smpte_percent", imd_res["imd"])
        
        print(f"IMD SMPTE: {imd_res['imd_db']:.2f} dB")
        
        assert imd_res["imd_db"] < -10.0, f"IMD too high: {imd_res['imd_db']:.2f} dB"

