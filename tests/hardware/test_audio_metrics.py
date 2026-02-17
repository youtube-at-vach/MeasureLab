import json
import time
import pytest
import numpy as np
from pathlib import Path
from src.core.audio_engine import AudioEngine
from src.core.analysis import AudioCalc
from src.gui.widgets.distortion_analyzer import DistortionAnalyzer

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware

class TestAudioHardwareMetrics:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        # Ensure we are in a known state
        self.engine.set_offline_mode(False) 
        
        # Instantiate the analyzer to access its logic
        self.analyzer = DistortionAnalyzer(self.engine)
        
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
        sr = 192000
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
        
        # Calculate THD+N using DistortionAnalyzer logic
        settings = {
            "signal_type": "sine",
            "sample_rate": sr,
            "window_type": self.analyzer.window_type, # Use widget default (blackmanharris)
            "gen_frequency": freq,
            "target_frequency": freq
        }
        
        metrics = DistortionAnalyzer.calculate_metrics(data, settings)
        
        thdn_db = metrics["thdn_db"]
        thdn_percent = metrics["thdn_percent"]
        sinad = metrics["sinad_db"]
        
        # Log properties for JSON report
        record_property("test_type", "THD+N")
        record_property("frequency_hz", float(freq))
        record_property("thdn_db", float(thdn_db))
        record_property("thdn_percent", float(thdn_percent))
        record_property("sinad_db", float(sinad))
        record_property("signal_rms", float(metrics["raw_fund_rms"]))
        record_property("noise_rms", float(metrics["raw_res_rms"]))
        
        # Thresholds (Configurable? For now flexible pass)
        assert thdn_db < -10.0, f"THD+N too high: {thdn_db:.2f} dB (Validation check)"



    def test_imd_smpte(self, record_property):
        """
        SMPTE IMD Measurement (60Hz / 7kHz, 4:1).
        """
        sr = 192000
        duration = 2.0
        
        signal = self.generate_signal(sr, duration, "smpte", amp=0.5)
        recorded = self.run_measurement(signal, sr, duration)
        
        # Skip settline
        skip_samples = int(sr * 0.2)
        data = recorded[skip_samples:, 0]
        
        # Calculate IMD SMPTE using DistortionAnalyzer logic
        settings = {
            "signal_type": "smpte",
            "sample_rate": sr,
            "window_type": self.analyzer.window_type,
            "imd_f1": 60.0,
            "imd_f2": 7000.0
        }
        
        imd_res = DistortionAnalyzer.calculate_metrics(data, settings)
        
        record_property("test_type", "IMD SMPTE")
        record_property("imd_smpte_db", float(imd_res["imd_db"]))
        record_property("imd_smpte_percent", float(imd_res["imd"]))
        
        print(f"IMD SMPTE: {imd_res['imd_db']:.2f} dB")
        
        assert imd_res["imd_db"] < -10.0, f"IMD too high: {imd_res['imd_db']:.2f} dB"

