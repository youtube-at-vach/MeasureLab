
import pytest
import numpy as np
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

def test_sound_level_meter_impulse_logic():
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

def test_sound_level_meter_fast_logic():
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
