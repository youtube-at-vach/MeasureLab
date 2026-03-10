import numpy as np
import scipy.signal
import pytest
from unittest.mock import MagicMock
from src.gui.widgets.sound_level_meter import SoundLevelMeter

class MockAudioEngine:
    def __init__(self):
        self.sample_rate = 48000
        self.calibration = MagicMock()
        self.calibration.get_spl_offset_db.return_value = 0.0

    def register_callback(self, callback):
        return 1

    def unregister_callback(self, callback_id):
        pass

@pytest.fixture
def slm():
    engine = MockAudioEngine()
    slm = SoundLevelMeter(engine)
    slm.set_channel(0)
    return slm

class TestSoundLevelMeterLogic:
    def test_sound_level_meter_impulse_logic(self):
        engine = MockAudioEngine()
        slm = SoundLevelMeter(engine)

        # Use Z weighting to avoid A-weighting complications (though 1kHz is 0dB)
        slm.set_freq_weighting('Z')
        # Bandwidth filter is still active (20Hz highpass), so we need AC signal.

        # Test IMPULSE weighting
        slm.set_time_weighting('IMPULSE')
        slm.start_analysis()

        sr = 48000
        frames = 1024

        # 1kHz sine wave
        t = np.linspace(0, frames/sr, frames, endpoint=False)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        # Stack for stereo
        indata_sine = np.column_stack((sig_1k, sig_1k))

        # Run a few callbacks with silence to settle filters
        for _ in range(10):
            indata = np.zeros((frames, 2))
            slm.callback(indata, None, frames, None, None)

        assert slm.current_sq_val == 0.0 or slm.current_sq_val < 1e-9

        # Inject signal (Sine wave)
        slm.callback(indata_sine, None, frames, None, None)

        # Impulse response should rise
        # value should be > 0
        assert slm.current_sq_val > 1e-6
        val_after_pulse = slm.current_sq_val

        # Silence again
        indata = np.zeros((frames, 2))
        slm.callback(indata, None, frames, None, None)

        # Impulse falls slowly (decay 1.5s) so it should still be high but slightly lower
        # However, since we fed a burst, the "Slow Fall" applies to the peak detector nature.
        # The stored value should decrease with tau=1.5s

        assert slm.current_sq_val < val_after_pulse
        # But shouldn't drop to zero instantly
        assert slm.current_sq_val > val_after_pulse * 0.9

        slm.stop_analysis()

    def test_sound_level_meter_fast_logic(self):
        engine = MockAudioEngine()
        slm = SoundLevelMeter(engine)

        slm.set_time_weighting('FAST')
        slm.start_analysis()

        sr = 48000
        frames = 1024
        t = np.linspace(0, frames/sr, frames, endpoint=False)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        indata_sine = np.column_stack((sig_1k, sig_1k))

        # Inject signal
        slm.callback(indata_sine, None, frames, None, None)

        assert slm.current_sq_val > 0.0

        slm.stop_analysis()

class TestSoundLevelMeterWeighting:
    def test_a_weighting_response(self, slm):
        """Verify A-weighting frequency response against IEC 61672 standard values."""
        slm.set_freq_weighting('A')
        # Force update filters
        slm._update_filters()

        sos = slm.sos_filter
        assert sos is not None, "A-weighting filter should not be None"

        # Standard A-weighting values (approx from IEC 61672-1:2003)
        # Freq (Hz): Expected Gain (dB)
        test_points = {
            63: -26.2,
            100: -19.1,
            125: -16.1,
            250: -8.6,
            500: -3.2,
            1000: 0.0,
            2000: 1.2,
            4000: 1.0,
            8000: -1.1,
            16000: -6.6
        }

        fs = slm.audio_engine.sample_rate

        for freq, expected_db in test_points.items():
            w, h = scipy.signal.sosfreqz(sos, worN=[freq], fs=fs)
            measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)

            # Tolerance: 1.0 dB generally, but 4.0 dB for 16kHz due to digital roll-off near Nyquist
            tol = 4.0 if freq >= 16000 else 1.0

            # Using print for debug if it fails
            if abs(measured_db - expected_db) >= tol:
                print(f"DEBUG: Freq {freq}Hz, Expected {expected_db}, Got {measured_db:.2f}")

            assert abs(measured_db - expected_db) < tol, \
                f"A-Weighting failed at {freq}Hz: Expected {expected_db}, got {measured_db:.2f}"

    def test_c_weighting_response(self, slm):
        """Verify C-weighting frequency response against IEC 61672 standard values."""
        slm.set_freq_weighting('C')
        slm._update_filters()

        sos = slm.sos_filter
        assert sos is not None, "C-weighting filter should not be None"

        test_points = {
            63: -0.8,
            125: -0.2,
            250: 0.0,
            500: 0.0,
            1000: 0.0,
            2000: -0.2,
            4000: -0.8,
            8000: -3.0,
            16000: -8.5
        }

        fs = slm.audio_engine.sample_rate

        for freq, expected_db in test_points.items():
            w, h = scipy.signal.sosfreqz(sos, worN=[freq], fs=fs)
            measured_db = 20 * np.log10(np.abs(h[0]) + 1e-12)

            tol = 4.0 if freq >= 16000 else 1.0
            assert abs(measured_db - expected_db) < tol, \
                f"C-Weighting failed at {freq}Hz: Expected {expected_db}, got {measured_db:.2f}"

    def test_z_weighting_response(self, slm):
        """Verify Z-weighting is flat (no filter)."""
        slm.set_freq_weighting('Z')
        slm._update_filters()

        # Z weighting usually means flat, so filter might be None or Identity
        # Implementation: self.sos_filter = None
        assert slm.sos_filter is None, "Z-weighting should have no filter (flat)"

    def test_filter_application_via_callback(self, slm):
        """Verify that the frequency weighting is applied during signal processing."""
        slm.set_freq_weighting('A')
        slm.set_time_weighting('FAST')
        slm.start_analysis()

        sr = slm.audio_engine.sample_rate
        duration = 2.0 # seconds (increased to ensure full settling of filters and time weighting)
        frames = int(sr * duration)
        t = np.linspace(0, duration, frames, endpoint=False)

        # 1. Test 1kHz (0dB gain)
        sig_1k = np.sin(2 * np.pi * 1000 * t)
        indata_1k = np.column_stack((sig_1k, sig_1k))

        # Process in chunks
        chunk_size = 1024
        for i in range(0, frames, chunk_size):
            chunk = indata_1k[i:i+chunk_size]
            if len(chunk) < chunk_size:
                break
            slm.callback(chunk, None, len(chunk), None, None)

        level_1k_db = slm.results["Lp"]

        # Reset
        slm.stop_analysis()
        slm.reset_measurements()
        slm.start_analysis()

        # 2. Test 100Hz (A-weighting: -19.1 dB)
        sig_100 = np.sin(2 * np.pi * 100 * t)
        indata_100 = np.column_stack((sig_100, sig_100))

        for i in range(0, frames, chunk_size):
            chunk = indata_100[i:i+chunk_size]
            if len(chunk) < chunk_size:
                break
            slm.callback(chunk, None, len(chunk), None, None)

        level_100_db = slm.results["Lp"]

        # Difference should be approx 19.1 dB
        diff = level_1k_db - level_100_db
        # Expected: 0 - (-19.1) = 19.1

        # Tolerance 1.5 dB because of settling time
        assert abs(diff - 19.1) < 1.5, \
            f"Callback A-weighting check failed. 1kHz: {level_1k_db}, 100Hz: {level_100_db}, Diff: {diff}"
