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

def pytest_generate_tests(metafunc):
    """
    Generate test cases based on --hardware-mode option.
    'typical': Run a single representative case (-6dBFS, Avg 10).
    'limit': Run matrix of amplitudes and averaging counts.
    """
    if "target_dbfs" in metafunc.fixturenames and "averaging_count" in metafunc.fixturenames:
        mode = metafunc.config.getoption("hardware_mode")
        
        if mode == "typical":
            # Fixed typical values
            metafunc.parametrize("target_dbfs", [-6.0])
            metafunc.parametrize("averaging_count", [10])
        else:
            # Limit mode (Matrix test)
            # Amplitude sweep from -12dB to 0dB in 1dB steps
            db_values = list(range(-12, 1)) 
            metafunc.parametrize("target_dbfs", db_values)
            metafunc.parametrize("averaging_count", [1, 2, 5, 10, 20])

class TestAudioHardwareMetrics:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        # Ensure we are in a known state
        self.engine.set_offline_mode(False) 
        
        # Instantiate the analyzer
        self.analyzer = DistortionAnalyzer(self.engine)
        
        yield
        
        # Stop analyzer if running
        if self.analyzer.is_running:
            self.analyzer.stop_analysis()
        
        if self.engine.is_active():
            self.engine.stop_stream()

    def run_analyzer_measurement(self, duration_sec):
        """
        Helper to run measurement using the Analyzer's internal logic.
        """
        # Ensure analyzer is running (starts the callback)
        if not self.analyzer.is_running:
            self.analyzer.start_analysis()
        
        self.analyzer.reset_averaging_state()
        
        results_list = []
        loop_start = time.time()
        
        # Wait a bit for the stream to stabilize before collecting data?
        # The analyzer logic handles initial startup, but we might get some zeros.
        time.sleep(0.5) 
        
        print(f"Starting measurement loop for {duration_sec}s...")
        
        while time.time() - loop_start < duration_sec:
            # Request capture from the running callback
            self.analyzer.request_capture()
            
            # Wait for data to be ready
            timeout = 0
            while not self.analyzer.capture_ready and timeout < 100:
                time.sleep(0.01)
                timeout += 1
            
            if self.analyzer.capture_ready:
                # Prepare settings for calculation (mirroring RealtimeAnalysisWorker)
                settings = {
                    "signal_type": self.analyzer.signal_type,
                    "sample_rate": self.engine.sample_rate,
                    "window_type": self.analyzer.window_type,
                    "gen_frequency": self.analyzer.gen_frequency,
                    "imd_f1": self.analyzer.imd_f1,
                    "imd_f2": self.analyzer.imd_f2,
                    "target_frequency": self.analyzer.gen_frequency # Assuming fixed freq
                }
                
                try:
                    # Perform calculation using the captured buffer
                    # Note: calculate_metrics is static
                    raw = DistortionAnalyzer.calculate_metrics(self.analyzer.captured_buffer, settings)
                    
                    # Apply averaging (instance method)
                    if raw["type"] == "imd":
                        final = self.analyzer._apply_imd_averaging(raw)
                    else:
                        final = self.analyzer._apply_result_averaging(raw)
                    
                    results_list.append(final)
                    
                except Exception as e:
                    print(f"Calculation error: {e}")
            
            # Analysis rate (approx 10Hz)
            time.sleep(0.1) 
            
        print(f"Captured {len(results_list)} results.")
        return results_list


    def test_thdn_1khz(self, target_dbfs, averaging_count, record_property):
        """
        THD+N check with matrix testing support.
        """
        sr = 192000
        
        # Calculate Bin Center Frequency
        # self.analyzer.buffer_size is 16384 by default
        bin_width = sr / self.analyzer.buffer_size
        freq_bin_idx = round(1000.0 / bin_width)
        freq = freq_bin_idx * bin_width
        
        # Configure Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_block_size(1024)
        
        # Configure Analyzer
        self.analyzer.signal_type = "sine"
        self.analyzer.gen_frequency = freq
        self.analyzer.gen_amplitude = 10**(target_dbfs/20.0)
        self.analyzer.average_count = averaging_count
        self.analyzer.window_type = "blackmanharris"
        self.analyzer.output_enabled = True # Essential for signal generation!
        
        # Run Measurement
        # Duration: wait long enough to get statistically significant samples
        settling_time = max(1.0, averaging_count * 0.1)
        test_duration = settling_time + 2.0 
        
        print(f"\nTesting THD+N: {target_dbfs} dBFS, Avg {averaging_count}")
        
        results = self.run_analyzer_measurement(test_duration)
        
        # Analysis of results
        samples_to_analyze = 10
        if len(results) < samples_to_analyze:
                samples_to_analyze = len(results) // 2
        
        if not results:
             pytest.fail("No results captured.")

        recent_results = results[-samples_to_analyze:]
        thdn_values = [r["thdn_db"] for r in recent_results]
        
        # Statistics
        mean_thdn = np.mean(thdn_values)
        std_thdn = np.std(thdn_values)
        
        print(f"  Mean THD+N: {mean_thdn:.2f} dB")
        print(f"  Std Dev: {std_thdn:.4f} dB")
        
        # Log properties
        record_property("test_type", "THD+N Matrix")
        record_property("target_dbfs", float(target_dbfs))
        record_property("averaging_count", averaging_count)
        record_property("frequency_hz", float(freq))
        record_property("thdn_db_mean", float(mean_thdn))
        record_property("thdn_db_std", float(std_thdn))
        
        # Signal Level Check
        last_fund_rms = recent_results[-1].get("raw_fund_rms", 0.0)
        measured_dbfs = 20 * np.log10(last_fund_rms * np.sqrt(2) + 1e-12)
        print(f"  Measured Signal Level: {measured_dbfs:.2f} dBFS")
        
        # Assertions (Soft check, outputting warning if it fails but not crashing unless critical)
        if target_dbfs > -10:
                if mean_thdn > -60.0:
                    print(f"  FAILED: THD+N {mean_thdn:.2f} dB is too high. Target around -80dB.")
                assert mean_thdn < -60.0, f"THD+N too high at {target_dbfs}dBFS: {mean_thdn:.2f} dB"


    def test_imd_smpte(self, target_dbfs, averaging_count, record_property):
        """
        SMPTE IMD Measurement with matrix testing.
        """
        sr = 192000
        
        self.engine.set_sample_rate(sr)
        
        # Configure Analyzer for SMPTE
        self.analyzer.signal_type = "smpte"
        self.analyzer.imd_f1 = 60.0
        self.analyzer.imd_f2 = 7000.0
        self.analyzer.gen_amplitude = 10**(target_dbfs/20.0)
        self.analyzer.average_count = averaging_count
        self.analyzer.output_enabled = True
        
        # Run Measurement
        settling_time = max(1.0, averaging_count * 0.1)
        test_duration = settling_time + 2.0
        
        print(f"\nTesting IMD SMPTE: {target_dbfs} dBFS, Avg {averaging_count}")
        
        results = self.run_analyzer_measurement(test_duration)
        
        samples_to_analyze = 10
        if len(results) < samples_to_analyze:
                samples_to_analyze = len(results) // 2
        
        if not results:
             pytest.fail("No results captured.")

        recent_results = results[-samples_to_analyze:]
        imd_values = [r["imd_db"] for r in recent_results]
        
        mean_imd = np.mean(imd_values)
        std_imd = np.std(imd_values)
        
        print(f"  Mean IMD: {mean_imd:.2f} dB")
        print(f"  Std Dev: {std_imd:.4f} dB")
        
        record_property("test_type", "IMD SMPTE Matrix")
        record_property("target_dbfs", float(target_dbfs))
        record_property("averaging_count", averaging_count)
        record_property("imd_db_mean", float(mean_imd))
        record_property("imd_db_std", float(std_imd))
        
        if target_dbfs > -10:
            assert mean_imd < -60.0, f"IMD too high: {mean_imd:.2f} dB"
