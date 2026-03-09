import numpy as np

from src.core.sonifier import Sonifier

def test_sonifier_initialization():
    s = Sonifier(sample_rate=48000)
    assert s.sample_rate == 48000
    assert not s.enabled
    assert s.mode == Sonifier.MODE_LEVEL_MONITOR
    assert s.master_volume == 0.5
    assert s.output_channel == 2

def test_sonifier_setters():
    s = Sonifier()
    s.set_enabled(True)
    assert s.enabled

    s.set_mode(Sonifier.MODE_FREQUENCY_MAPPING)
    assert s.mode == Sonifier.MODE_FREQUENCY_MAPPING

    s.set_volume(0.8)
    assert s.master_volume == 0.8

    s.set_manual_freq(500.0)
    assert s.manual_freq == 500.0

    s.set_output_channel(0)
    assert s.output_channel == 0

def test_sonifier_process_disabled():
    s = Sonifier()
    outdata = np.ones((1024, 2))
    s.process(outdata)
    # Since it's disabled and amp is 0, it should zero the buffer
    assert np.all(outdata == 0.0)

def test_sonifier_process_enabled_level_monitor():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_mode(Sonifier.MODE_LEVEL_MONITOR)

    # Update with some noise
    s.update_parameters(scan_freq=1000.0, mag_db=-50.0)

    outdata = np.zeros((1024, 2))
    s.process(outdata)

    # Target freq should be 800.0
    assert s.current_freq == 800.0

    # Should not be all zeros
    assert np.any(outdata != 0.0)

    # Test output channel routing (Left only)
    s.set_output_channel(0)
    outdata = np.zeros((1024, 2))
    s.process(outdata)
    assert np.any(outdata[:, 0] != 0.0)
    assert np.all(outdata[:, 1] == 0.0)

    # Right only
    s.set_output_channel(1)
    outdata = np.zeros((1024, 2))
    s.process(outdata)
    assert np.all(outdata[:, 0] == 0.0)
    assert np.any(outdata[:, 1] != 0.0)

def test_sonifier_frequency_mapping():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_mode(Sonifier.MODE_FREQUENCY_MAPPING)

    s.update_parameters(scan_freq=1234.5, mag_db=-20.0) # Max amp

    outdata = np.zeros((1024, 2))
    s.process(outdata)

    assert s.current_freq == 1234.5

def test_sonifier_manual_tuner():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_mode(Sonifier.MODE_MANUAL_TUNER)
    s.set_manual_freq(777.0)

    s.update_manual_tuner_mag(mag_db=-40.0)

    outdata = np.zeros((1024, 2))
    s.process(outdata)

    assert s.current_freq == 777.0

def test_sonifier_normalization_makes_moderate_levels_audible():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_mode(Sonifier.MODE_LEVEL_MONITOR)

    for _ in range(12):
        s.update_parameters(scan_freq=1000.0, mag_db=-105.0)

    s.update_parameters(scan_freq=1000.0, mag_db=-98.0)

    assert s.target_amp > 0.05
    assert s.target_amp <= s.SONIFICATION_MAX_PEAK * s.master_volume

def test_sonifier_normalization_mutes_below_noise_floor():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)

    s.update_parameters(scan_freq=1000.0, mag_db=-160.0)

    assert s.target_amp == 0.0

def test_sonifier_normalization_caps_loud_signals():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_volume(1.0)

    for _ in range(8):
        s.update_parameters(scan_freq=1000.0, mag_db=-90.0)
    s.update_parameters(scan_freq=1000.0, mag_db=0.0)

    assert s.target_amp > 0.20
    assert s.target_amp <= s.SONIFICATION_MAX_PEAK

def test_sonifier_adaptive_context_follows_noise_floor_band():
    s = Sonifier(sample_rate=48000)
    s.set_enabled(True)

    for level in (-108.0, -107.5, -107.0, -106.5, -106.0, -105.5):
        s.update_parameters(scan_freq=1000.0, mag_db=level)

    low_amp = s.target_amp
    s.update_parameters(scan_freq=1000.0, mag_db=-101.0)
    high_amp = s.target_amp

    assert high_amp > low_amp
    assert high_amp > 0.04
