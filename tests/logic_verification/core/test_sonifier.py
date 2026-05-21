import numpy as np

from src.core.sonifier import Sonifier


def test_sonifier_initialization():
    s = Sonifier(sample_rate=48000)
    assert s.sample_rate == 48000
    assert not s.enabled
    assert s.mode == Sonifier.MODE_LEVEL_MONITOR
    assert s.master_volume_db == 0.0
    assert s.output_channel == 2


def test_sonifier_setters():
    s = Sonifier()
    s.set_enabled(True)
    assert s.enabled

    s.set_mode(Sonifier.MODE_FREQUENCY_MAPPING)
    assert s.mode == Sonifier.MODE_FREQUENCY_MAPPING

    s.set_volume(-10.0)
    assert s.master_volume_db == -10.0

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

    s.update_parameters(scan_freq=1234.5, mag_db=-20.0)  # Max amp

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


def test_sonifier_at_140dbfs():
    s = Sonifier()
    s.set_enabled(True)
    s.set_volume(60.0)  # +60dB boost
    s.update_parameters(scan_freq=1000.0, mag_db=-140.0)
    # -140 + 60 = -80.
    # normalized_amp = (-80 - (-100)) / (-20 - (-100)) = 20 / 80 = 0.25
    # target_amp = 0.25**3 = 0.015625
    assert np.isclose(s.target_amp, 0.25**3)


def test_sonifier_set_sample_rate():
    s = Sonifier()
    s.set_sample_rate(96000)
    assert s.sample_rate == 96000

    s.set_sample_rate(0)
    assert s.sample_rate == 0
