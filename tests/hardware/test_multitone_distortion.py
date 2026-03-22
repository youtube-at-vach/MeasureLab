import pytest
import numpy as np
import time
from src.core.audio_engine import AudioEngine
from src.gui.widgets.advanced_distortion_meter import AdvancedDistortionMeter
from src.core.analysis import AudioCalc

# Mark entire module as hardware tests
pytestmark = pytest.mark.hardware


def pytest_generate_tests(metafunc):
    """
    Generate test cases based on --hardware-mode option.
    'typical': Run a single representative case (31 tones, ~5s, -6dBFS).
    'limit': Matrix test.
             Amplitudes: -24 to 0 dBFS in 6dB steps.
             Tone counts: 31, 63.
    """
    if "mim_params" in metafunc.fixturenames:
        mode = metafunc.config.getoption("hardware_mode")

        if mode == "typical":
            # Typical: 31 tones, standard buffer, -6dBFS
            metafunc.parametrize(
                "mim_params", [{"tone_count": 31, "buffer_size": 65536, "duration_sec": 5.0, "amp_dbfs": -12.0}]
            )
        else:
            # Limit: Matrix
            amplitudes = [-24.0, -18.0, -12.0, -6.0, 0.0]
            tone_counts = [31, 63]

            cases = []
            for tc in tone_counts:
                for amp in amplitudes:
                    cases.append(
                        {
                            "tone_count": tc,
                            "buffer_size": 65536,
                            "duration_sec": 5.0,  # 5s is enough for capture
                            "amp_dbfs": amp,
                        }
                    )

            metafunc.parametrize("mim_params", cases)


class TestMultitoneDistortion:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for hardware tests."""
        self.engine = AudioEngine()
        self.engine.set_offline_mode(False)
        self.meter = AdvancedDistortionMeter(self.engine)
        yield
        if self.meter.is_running:
            self.meter.stop_analysis()
        if self.engine.is_active():
            self.engine.stop_stream()

    def test_multitone_tdn(self, mim_params, record_property, hardware_config):
        """
        Measures Multitone Distortion + Noise (TD+N) using MIM method.
        """
        sr = hardware_config.get("sample_rate", 48000)
        input_device = hardware_config.get("input_device")
        output_device = hardware_config.get("output_device")

        tone_count = mim_params["tone_count"]
        buffer_size = mim_params["buffer_size"]
        amp_dbfs = mim_params["amp_dbfs"]

        # Configure Audio Engine
        self.engine.set_sample_rate(sr)
        self.engine.set_devices(input_device, output_device)

        # Log Hardware Config
        record_property("test_type", "Multitone Distortion")
        record_property("sample_rate", sr)
        record_property("buffer_size", buffer_size)
        record_property("tone_count", tone_count)
        record_property("amp_dbfs", amp_dbfs)

        # Configure Meter
        self.meter.buffer_size = buffer_size
        self.meter.mim_tone_count = tone_count
        self.meter.mode = "MIM"
        self.meter.mim_min_freq = 20.0
        self.meter.mim_max_freq = 20000.0

        # Loopback Mode
        # Ref Output: Ch1 (L), Signal Input: Ch1 (L)
        self.meter.output_channel = 0
        self.meter.input_channel = 0
        self.meter.output_enabled = True

        # Convert dBFS to Linear
        # 0 dBFS = 1.0
        linear_amp = 10 ** (amp_dbfs / 20.0)
        self.meter.gen_amplitude = linear_amp

        # Start Analysis
        self.meter.start_analysis()

        # The AdvancedDistortionMeter is state-machine based.
        # It goes MEASURING -> DONE.

        print(f"\nStarting Multitone Measurement ({tone_count} tones)...")

        # 1. Warm-up Cycle (to flush loopback latency)
        # We capture one buffer (which will contain silence/transient) and discard it.
        # The output continues running, so the next capture will be steady-state.

        # Helper to wait for capture
        def wait_for_capture(timeout=10.0):
            start = time.time()
            while time.time() - start < timeout:
                if self.meter.state == self.meter.STATE_DONE:
                    return True
                time.sleep(0.01)
            return False

        if not wait_for_capture():
            pytest.fail("Warm-up capture timed out")

        # 2. Actual Measurement
        self.meter.reset_measurement()

        if not wait_for_capture():
            pytest.fail("Measurement capture timed out")

        # Retrieve buffer
        rec_buffer = self.meter.recording_buffer

        # Check signal level
        rms = np.sqrt(np.mean(rec_buffer**2))
        rms_db = 20 * np.log10(rms + 1e-12)
        print(f"Captured RMS: {rms_db:.2f} dBFS")
        record_property("input_rms_dbfs", rms_db)

        if rms_db < -60.0:
            pytest.fail(f"Input signal too low ({rms_db:.2f} dBFS). Check loopback connection.")

        # Analysis
        # Re-use logic from AnalysisWorker/DistortionAnalyzer
        # 1. Compute Spectrum
        # Use "boxcar" (rectangular) window for Coherent Sampling
        freqs, mag_linear, fft_res = AudioCalc._compute_spectrum(rec_buffer, "boxcar", sr)
        # Note: MIM uses Coherent sampling with Rectangular window usually,
        # effectively no window if buffer is multiple of period.
        # AdvancedDistortionMeter uses random phase multitone locked to bin centers.
        # So "rectangular" (uniform) window key might be needed or just passed as None/boxcar?
        # AudioCalc._compute_spectrum takes window_name. "boxcar" or "rectangular"?
        # scipy.signal.get_window supports "boxcar".

        # 2. Get expected frequencies
        # We need to access the generated frequencies from the meter
        if self.meter._mim_freqs is None:
            # Should have been generated during start_analysis -> _update_output_buffer
            # But _update_output_buffer is called in start_analysis.
            pass

        mim_freqs = self.meter._mim_freqs

        # 3. Calculate TD+N
        metrics = AudioCalc.calculate_multitone_tdn(mag_linear, freqs, mim_freqs)

        tdn_db = metrics["tdn_db"]
        tdn_percent = metrics["tdn"]

        print("\nResults:")
        print(f"  TD+N: {tdn_db:.2f} dB")
        print(f"  TD+N: {tdn_percent:.4f} %")

        record_property("tdn_db", tdn_db)
        record_property("tdn_percent", tdn_percent)

        # Validations
        # Based on measurement results:
        # -6 dBFS: ~ -34 dB TD+N
        # 0 dBFS:  ~ -14 dB TD+N (Likely clipping/limiting)
        # Lower amplitudes (< -6 dBFS) should be better or similar (limited by noise floor but relative level holds > 30dB)

        limit_db = -20.0
        if amp_dbfs > -3.0:
            limit_db = -10.0

        assert tdn_db < limit_db, f"TD+N too high: {tdn_db:.2f} dB (Limit: {limit_db} dB)"
