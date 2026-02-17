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
        # DIAGNOSTIC: Enable loopback to rule out code issues vs hardware issues.
        # If this passes, the code is correct but hardware loopback is missing.
        # The user report implies "Sound not coming out", so maybe output device is wrong.
        # But let's check software loopback first.
        # self.engine.set_loopback(True) 
        
        # Instantiate the analyzer
        self.analyzer = DistortionAnalyzer(self.engine)
        
        yield
        
        # Stop analyzer if running
        self.analyzer.is_running = False
        
        if self.engine.is_active():
            self.engine.stop_stream()

    def run_analyzer_measurement(self, duration_sec, max_retries=3):
        """
        Helper to run measurement.
        Since we don't have the GUI's RealtimeAnalysisWorker, we must manually
        feed data to the analyzer or rely on a callback that does so.
        """
        self.analyzer.is_running = True
        self.analyzer.reset_averaging_state()
        
        # We need to capture data coming FROM the engine (which includes our generated signal loopback)
        # and feed it to the analyzer.
        # The DistortionAnalyzer doesn't have a 'feed' method that accepts raw chunks purely for buffering?
        # Actually `process` takes data and returns metrics.
        
        # Strategy:
        # 1. Register a "Capture" callback on AudioEngine.
        # 2. In that callback, accumulate data.
        # 3. Periodically (or in the callback) call `DistortionAnalyzer.calculate_metrics`.
        #    BUT `calculate_metrics` is static.
        #    The `DistortionAnalyzer` instance stores state (averaging).
        #    We need to call `analyzer._apply_result_averaging`.
        
        # Let's create a thread-safe list to store results
        results_list = []
        
        # Capture Callback
        def capture_callback(indata, outdata, frames, time, status):
            if status:
                print(f"Status: {status}")
            
            # Debug input shape once
            if not hasattr(capture_callback, "logged_shape"):
                print(f"Audio Input Shape: {indata.shape}")
                capture_callback.logged_shape = True
            
            # Get input (Mono or Stereo -> Mono for analysis usually)
            # Analysis usually takes the first channel or selected channel.
            # Here indata is what we need.
            
            # We need to buffer enough data for analysis (e.g. 16k samples).
            # If we process every block (1024), we might not have enough resolution.
            # The GUI worker uses a RingBuffer.
            
            # Simpler approach for Test:
            # Just push `indata` to a local RingBuffer, and when full, analyze?
            # Or use `DistortionAnalyzer`'s logic?
            # `DistortionAnalyzer` itself doesn't have a RingBuffer exposed for external push?
            # Checking code... `self.input_data` in widget is updated via `update_realtime_analysis`.
            # That `input_data` comes from `worker.get_data()`.
            
            # So we need to replicate the Worker's buffering logic.
            pass

        # To avoid re-implementing RingBuffer, let's look at how the worker does it.
        # The worker `src/gui/workers/realtime_analysis_worker.py` presumably uses `AudioEngine.register_callback` 
        # or just reads from a stream?
        # Actually `AudioEngine` callbacks are push-based.
        
        # Let's implement a simple buffering mechanism here.
        # We need a continuous buffer for analysis (16k samples).
        buffer_size = 16384 
        current_buffer = np.zeros(buffer_size, dtype=np.float32)
        # We use a rolling buffer approach: 
        # Always append new data to the end, shifting old data out.
        # This acts like a delay line / FIFO.
        
        def processing_callback(indata, outdata, frames, time, status):
            nonlocal current_buffer
            
            # Use channel 0 for analysis
            if indata.ndim > 1:
                mono_in = indata[:, 0]
            else:
                mono_in = indata
                
            chunk_len = len(mono_in)
            
            # Shift buffer content to the left
            current_buffer = np.roll(current_buffer, -chunk_len)
            # Overwrite the end with new data
            current_buffer[-chunk_len:] = mono_in
            
            # We don't analyze inside the callback to avoid blocking audio thread.
            # The test loop will poll `current_buffer` via `analyzer.request_capture()`... 
            # WAIT. `request_capture` in `analyzer` just sets a flag.
            # `DistortionAnalyzer` (the widget class) usually reads from `self.input_data` in its own timer loop.
            # In our test `run_analyzer_measurement`, we are calling `request_capture`.
            # But `DistortionAnalyzer` has no internal thread running to update `input_data`.
            
            # CRITICAL: We need to update `self.analyzer.input_data` here!
            # The `DistortionAnalyzer` has a method or logic to update `input_data`.
            # In the widget, `callback` does:
            # self.input_data[:] = new_data[-self.buffer_size :] (if large) or roll.
            
            # So we should just update `self.analyzer.input_data` directly here!
            # Thread safety: `input_data` is numpy array. 
            # In Python, assignment is atomic-ish, but `roll` and `copy` are not.
            # However, for a test it's likely fine, or we use a lock if needed.
            # `DistortionAnalyzer` uses `self.input_data` as the source for `captured_buffer`.
            
            # Update analyzer's buffer
            # We can literally reuse the logic from `DistortionAnalyzer.callback` (if we could call it).
            # But we are in `processing_callback`.
            
            # Direct update:
            if chunk_len >= buffer_size:
                self.analyzer.input_data[:] = mono_in[-buffer_size:]
            else:
                self.analyzer.input_data = np.roll(self.analyzer.input_data, -chunk_len)
                self.analyzer.input_data[-chunk_len:] = mono_in
                
            # Handle Capture Request in the Callback (emulating widget behavior)
            if self.analyzer.capture_requested:
                # Debug signal level
                rms = np.sqrt(np.mean(self.analyzer.input_data**2))
                if rms < 1e-6:
                     print(f"Warning: Captured silence (RMS={rms})")
                
                self.analyzer.captured_buffer = self.analyzer.input_data.copy()
                self.analyzer.capture_requested = False
                self.analyzer.capture_ready = True
                
        # Register processing callback
        print("Registering processing callback...")
        cid = self.engine.register_callback(processing_callback)
        
        try:
            # Wait for duration
            print(f"Waiting for {duration_sec}s measurement...")
            # We need to loop here to allow the test method (caller) to handle results?
            # NO, this method returns `results_list`.
            # But `processing_callback` doesn't populate `results_list`.
            # `processing_callback` only updates `Captured Buffer`.
            # WE MISSING THE ANALYSIS LOOP!
            
            # The previous logic had a `while` loop that called `request_capture` and then `calculate_metrics`.
            # But I removed it and replaced it with `time.sleep(duration_sec)` in the `multi_replace` at Step 175.
            # I deleted the loop that actually does the calculation and appends to `results_list`.
            
            # RESTORE THE ANALYSIS LOOP using the new callback for data feeding.
            
            loop_start = time.time()
            while time.time() - loop_start < duration_sec:
                self.analyzer.request_capture()
                
                # Wait for data (filled by callback)
                timeout = 0
                while not self.analyzer.capture_ready and timeout < 100:
                    time.sleep(0.01)
                    timeout += 1
                
                if self.analyzer.capture_ready:
                    # Calculate
                    settings = {
                        "signal_type": self.analyzer.signal_type,
                        "sample_rate": self.engine.sample_rate,
                        "window_type": self.analyzer.window_type,
                        "gen_frequency": self.analyzer.gen_frequency,
                        "imd_f1": self.analyzer.imd_f1,
                        "imd_f2": self.analyzer.imd_f2
                    }
                    
                    try:
                        raw = DistortionAnalyzer.calculate_metrics(self.analyzer.captured_buffer, settings)
                        if raw["type"] == "imd":
                            final = self.analyzer._apply_imd_averaging(raw)
                        else:
                            final = self.analyzer._apply_result_averaging(raw)
                        results_list.append(final)
                    except Exception as e:
                        print(f"Calc error: {e}")
                        
                time.sleep(0.1) # 10Hz analysis rate
                
        finally:
            self.engine.unregister_callback(cid)
            print(f"Captured {len(results_list)} results.")
            
        return results_list


    def test_thdn_1khz(self, target_dbfs, averaging_count, record_property):
        """
        THD+N check with matrix testing support.
        """
        sr = 48000 # Standard rate for analyzer
        freq = 1000.0
        
        # Configure Analyzer
        self.analyzer.signal_type = "sine"
        self.analyzer.gen_frequency = freq
        self.analyzer.gen_amplitude = 10**(target_dbfs/20.0) # Convert dBFS to linear
        self.analyzer.average_count = averaging_count
        self.analyzer.window_type = "blackmanharris" # Default
        
        # Configure Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_block_size(1024) # Internal block size
        # Analyzer uses its own buffer size logic (ring buffer), usually default 16k
        
        # Setup Generator Callback
        total_frames = 0
        def generator_callback(outdata, frames, time_info, status):
            nonlocal total_frames
            t = (total_frames + np.arange(frames)) / sr
            total_frames += frames
            
            # Sine Wave
            sig = self.analyzer.gen_amplitude * np.sin(2*np.pi*self.analyzer.gen_frequency*t)
            
            # Write to output
            outdata[:, 0] = sig
            if outdata.shape[1] > 1:
                outdata[:, 1] = sig

        # Register Generator
        cid = None
        try:
             # Stop any existing stream? 
             # AudioEngine manages stream internally. Just register.
             cid = self.engine.register_callback(generator_callback)

             # Run Measurement Loop
             # Duration: wait long enough to get statistically significant samples *after* averaging stabilizes
             # For avg=20, we need at least 20 samples to fill history.
             # At 10Hz update rate, that's 2 seconds.
             # Let's run for sufficient time + 10 iterations
             settling_time = max(1.0, averaging_count * 0.1)
             test_duration = settling_time + 2.0 
             
             print(f"\nTesting THD+N: {target_dbfs} dBFS, Avg {averaging_count}")
             
             results = self.run_analyzer_measurement(test_duration)
             
             # Extract THD+N values from the last N samples (stabilized)
             samples_to_analyze = 10
             if len(results) < samples_to_analyze:
                  samples_to_analyze = len(results) // 2
                  
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
             
             # Assertions
             # 1. Signal level check (approximate)
             last_res = recent_results[-1]
             # measured_db = 20 * np.log10(last_res["raw_fund_rms"] * np.sqrt(2) + 1e-12) 
             
             # 2. THD+N check
             # 2. THD+N check
             measured_rms = np.sqrt(np.mean(np.array(thdn_values)**2)) # This is wrong, thdn_values are dB? No, they are values.
             # Recalculate RMS from the last result raw data if available?
             # recent_results has "raw_fund_rms".
             
             last_fund_rms = recent_results[-1].get("raw_fund_rms", 0.0)
             measured_dbfs = 20 * np.log10(last_fund_rms * np.sqrt(2) + 1e-12)
             print(f"  Measured Signal Level: {measured_dbfs:.2f} dBFS")
             
             if target_dbfs > -10:
                  if mean_thdn > -60.0:
                      print(f"  FAILED: THD+N {mean_thdn:.2f} dB is too high. Target around -80dB.")
                      print(f"  Possible causes: Loopback cable missing, gain mismatch, or noise.")
                  assert mean_thdn < -60.0, f"THD+N too high at {target_dbfs}dBFS: {mean_thdn:.2f} dB (Level: {measured_dbfs:.2f} dBFS)"
                  
        finally:
             if cid is not None:
                 self.engine.unregister_callback(cid)


    def test_imd_smpte(self, target_dbfs, averaging_count, record_property):
        """
        SMPTE IMD Measurement with matrix testing.
        """
        sr = 48000
        
        # Configure Analyzer
        self.analyzer.signal_type = "smpte"
        self.analyzer.imd_f1 = 60.0
        self.analyzer.imd_f2 = 7000.0
        # IMD signal generation:
        # 4:1 ratio. The gen_amplitude sets the peak sum.
        # Logic matches DistortionAnalyzer.run() / generate_signal (internal)
        # We rely on DistortionAnalyzer.input_data generation which is driven by AudioEngine callbacks?
        # WAIT: DistortionAnalyzer is a Consumer/Analysis module. 
        # It has a "Generator" part?
        # Looking at DistortionAnalyzer code, it seems the generator logic is inside the `run()` method for Sweeps,
        # OR it assumes an external generator or internal generator set via `gen_frequency`/`gen_amplitude`.
        
        # Ideally, we used `generate_signal` helper in previous test.
        # But `DistortionAnalyzer` does NOT generate signal automatically in Real-time mode?
        # Actually it *does* if checking `gui/widgets/distortion_analyzer.py`:
        # "Output Mode" combo selects "Sine Wave", "SMPTE", etc.
        # And `update_realtime_analysis` reads input.
        # BUT: Who writes to output?
        # The `AudioEngine` callback needs to generate signal.
        # The `DistortionAnalyzer` widget usually connects to `AudioEngine` but does it register a render callback?
        # In `src/gui/widgets/distortion_analyzer.py`, we don't see explicit render callback registration in `__init__`.
        # It relies on `self.module.audio_engine`.
        
        # CRITICAL: We need to manually generate the signal if `DistortionAnalyzer` doesn't do it automatically
        # in the test environment.
        # Let's restore `generate_signal` and `run_measurement` callback approach?
        # NO, we want to use `DistortionAnalyzer` Capture.
        # The Capture just reads current input buffer.
        # We need something to drive the Output.
        
        # Solution: Register a generator callback on AudioEngine that generates the requested signal.
        self.analyzer.gen_amplitude = 10**(target_dbfs/20.0)
        self.analyzer.average_count = averaging_count
        
        # Setup Generator Callback
        total_frames = 0
        def generator_callback(outdata, frames, time_info, status):
            nonlocal total_frames
            t = (total_frames + np.arange(frames)) / sr
            total_frames += frames
            
            if self.analyzer.signal_type == "smpte":
                # SMPTE Logic
                amp = self.analyzer.gen_amplitude
                f1 = self.analyzer.imd_f1
                f2 = self.analyzer.imd_f2
                # 4:1 ratio => 5 parts.
                a_high = amp / 5.0
                a_low = 4.0 * a_high
                sig = a_low * np.sin(2*np.pi*f1*t) + a_high * np.sin(2*np.pi*f2*t)
            else:
                # Sine
                sig = self.analyzer.gen_amplitude * np.sin(2*np.pi*self.analyzer.gen_frequency*t)
            
            # Write to output (Mono to Stereo)
            outdata[:, 0] = sig
            if outdata.shape[1] > 1:
                outdata[:, 1] = sig
                
        # Register Generator
        cid = None
        try:
             # We can't easily access the existing stream's callback. 
             # But AudioEngine allows replacing/setting callback?
             # `AudioEngine` is usually Singleton-ish but here instantiated.
             # Actually `AudioEngine.register_callback` adds to a list?
             # No, `register_callback` in `test_audio_metrics.py` (previous version) was used.
             # `AudioEngine` class has `start_stream` which takes a callback.
             # If stream is already running (it might be), we need to stop and start.
             
             cid = self.engine.register_callback(generator_callback)
             
             # Run Measurement
             settling_time = max(1.0, averaging_count * 0.1)
             test_duration = settling_time + 2.0
             
             print(f"\nTesting IMD SMPTE: {target_dbfs} dBFS, Avg {averaging_count}")
             
             results = self.run_analyzer_measurement(test_duration)
             
             # Extract IMD values
             samples_to_analyze = 10
             if len(results) < samples_to_analyze:
                  samples_to_analyze = len(results) // 2
                  
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
                 
        finally:
             if cid is not None:
                 self.engine.unregister_callback(cid)

