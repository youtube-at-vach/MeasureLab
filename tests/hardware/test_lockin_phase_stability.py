import pytest
import numpy as np
import time
from src.core.audio_engine import AudioEngine
from src.gui.widgets.lock_in_frequency_counter import LockInFrequencyCounter

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware


def pytest_generate_tests(metafunc):
    """
    Generate test cases based on --hardware-mode option.
    'typical': Run a single representative case (~5s measurement).
    'limit': Run a longer duration case (~30s measurement) to test stability limits.
    """
    if "duration_sec" in metafunc.fixturenames:
        mode = metafunc.config.getoption("hardware_mode")

        if mode == "typical":
            # Typical: ~5 seconds
            metafunc.parametrize("duration_sec", [5.0])
            metafunc.parametrize("buffer_size", [8192])
        else:
            # Limit: ~30 seconds
            metafunc.parametrize("duration_sec", [30.0])
            metafunc.parametrize("buffer_size", [8192])


class TestLockinPhaseStability:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        self.engine.set_offline_mode(False)
        self.lockin = LockInFrequencyCounter(self.engine)
        yield
        if self.lockin.is_running:
            self.lockin.stop_analysis()
        if self.engine.is_active():
            self.engine.stop_stream()

    def test_phase_stability(self, duration_sec, buffer_size, record_property, hardware_config):
        """
        Measures Phase Stability (Phase RMS) and Time Interval Error (TIE)
        using LockInFrequencyCounter (Continous Phase Integration).
        This avoids the random walk drift associated with integrating frequency frequency counters.
        """
        sr = hardware_config.get("sample_rate", 48000)
        input_device = hardware_config.get("input_device")
        output_device = hardware_config.get("output_device")

        target_freq = 1000.0

        # Configure Audio Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_devices(input_device, output_device)

        # Log Hardware Config
        record_property("sample_rate", sr)
        record_property("buffer_size", buffer_size)

        # Configure Lock-in Frequency Counter
        self.lockin.gen_frequency = target_freq
        self.lockin.buffer_size = buffer_size

        # Loopback Mode
        # Ref Output: Ch1 (L), Signal Input: Ch1 (L)
        self.lockin.ref_mode = "loopback"
        self.lockin.ref_channel = 0
        self.lockin.signal_channel = 0

        # Disable FLL and smoothing for raw stability measurement
        self.lockin.locked = False
        self.lockin.smoothing_tau = 0.0

        # Start Analysis
        self.lockin.start_analysis()

        # Wait for settling (buffer fill + initial transients)
        buffer_duration = buffer_size / sr
        time.sleep(max(1.0, buffer_duration * 5))

        print(f"\nStarting Measurement ({duration_sec}s)...")

        # Measurement Loop
        phases = []
        timestamps = []

        start_time = time.time()
        last_process = start_time

        while time.time() - start_time < duration_sec:
            current_time = time.time()

            # Process data roughly every buffer period
            if current_time - last_process >= buffer_duration:
                self.lockin.process_data()

                # Check for signal
                if not getattr(self.lockin, "signal_present", False):
                    # In real loopback, signal should be present. 
                    # If not, it might be just skipping a frame or setting up.
                    # We continue but don't record potentially bad data?
                    # Or we just rely on the buffer duration wait.
                    pass

                # Capture Accumulated Phase (Degrees)
                # This is already unwrapped/integrated phase
                p = self.lockin.current_phase_deg

                phases.append(p)
                timestamps.append(current_time - start_time)
                last_process = current_time
            else:
                time.sleep(max(0.001, buffer_duration / 10))

        # Analysis
        if len(phases) < 5:
            pytest.fail("Not enough data points collected")

        phases_unwrapped_deg = np.array(phases)
        # Note: LockInFrequencyCounter.current_phase_deg is accumulated phase, 
        # so it is already unwrapped.

        t = np.array(timestamps)

        # 1. Remove Linear Trend (Frequency Offset)
        slope, intercept = np.polyfit(t, phases_unwrapped_deg, 1)
        trend = slope * t + intercept
        residuals_deg = phases_unwrapped_deg - trend

        # 2. Calculate Metrics

        # Metric A: Short-term TIE (Jitter)
        # Detrended phase noise
        phase_jitter_rms_deg = np.std(residuals_deg)
        tie_rms_jitter_sec = phase_jitter_rms_deg / (360.0 * target_freq)

        # Metric B: Long-term TIE (Drift + Jitter)
        # Raw phase deviation (relative to linear fit)
        # Actually, "Drift" in TIE usually refers to the wander of the clock.
        # But here we are comparing against a fixed NCO.
        # If we remove the slope (frequency offset), the residuals are the TIE (Time Interval Error).
        # The slope itself is the frequency offset.

        # If we want TIE including the drift (deviation from ideal frequency),
        # we would compare against ideal phase (slope = 0 relative to target_freq).
        # But our NCO IS the target freq.
        # So phases_unwrapped_deg SHOULD be near 0 slope if freq is exact.
        # The slope IS the frequency error.

        # This corresponds to the "Frequency Counter" style TIE
        # But phases_unwrapped_deg grows indefinitely if there is offset.
        # We probably want the std deviation of the residuals for "Jitter".

        # For "Long Term Stability", maybe we look at how much the slope changes?
        # Or just reports the metrics as defined in previous test.

        metric_long_term_deg = np.std(phases_unwrapped_deg) 
        # This value is dominated by the slope if freq offset is non-zero.
        # Let's keep the logic from previous test for consistency if that was intentional.
        # Previous test: phase_total_std_deg = np.std(phases_unwrapped_deg)

        tie_rms_total_sec = metric_long_term_deg / (360.0 * target_freq)

        # Frequency Offset from Slope
        measured_freq_offset_hz = slope / 360.0

        # Log Metrics
        print(f"\nResults ({duration_sec}s):")
        print(f"  Freq Offset:     {measured_freq_offset_hz:.6f} Hz")
        print(f"  Phase RMS (Jit): {phase_jitter_rms_deg:.6f} deg")
        print(f"  TIE (Short):     {tie_rms_jitter_sec * 1e9:.3f} ns (Jitter)") 
        print(f"  TIE (Long):      {tie_rms_total_sec * 1e9:.3f} ns (Total)")


        record_property("test_type", "Phase Stability")
        record_property("duration_sec", duration_sec)
        record_property("freq_offset_hz", measured_freq_offset_hz)
        record_property("phase_jitter_rms_deg", phase_jitter_rms_deg)
        record_property("tie_rms_jitter_sec", tie_rms_jitter_sec)
        record_property("tie_rms_total_sec", tie_rms_total_sec)

        # Assertions
        # Check Short-term TIE (Jitter) is low
        assert tie_rms_jitter_sec < 1e-6, f"Short-term TIE too high: {tie_rms_jitter_sec * 1e9:.1f} ns"
