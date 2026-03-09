import numpy as np

from src.core.sonifier import PeakToneSonifier


def test_peak_tone_sonifier_initialization():
    s = PeakToneSonifier(sample_rate=48000)
    assert s.sample_rate == 48000
    assert not s.enabled
    assert s.master_volume == 0.5
    assert s.output_channel == 2
    assert s.max_peaks == 1


def test_peak_tone_sonifier_setters():
    s = PeakToneSonifier()
    s.set_enabled(True)
    assert s.enabled

    s.set_volume(0.8)
    assert s.master_volume == 0.8

    s.set_output_channel(0)
    assert s.output_channel == 0

    s.set_max_peaks(3)
    assert s.max_peaks == 3


def test_peak_tone_sonifier_process_outputs_tone():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.update_peaks([1000.0])

    outdata = np.zeros((1024, 2))
    s.process(outdata)

    assert np.any(outdata != 0.0)


def test_peak_tone_sonifier_folds_to_audible_band():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_max_peaks(2)
    s.update_peaks([32000.0, 40.0])

    assert np.all(s._active_freqs >= s.AUDIBLE_MIN_FREQ)
    assert np.all(s._active_freqs <= s.AUDIBLE_MAX_FREQ)


def test_peak_tone_sonifier_process_disabled():
    s = PeakToneSonifier()
    outdata = np.ones((256, 2))

    s.process(outdata)

    assert np.all(outdata == 0.0)


def test_peak_tone_sonifier_skips_unchanged_peak_update():
    s = PeakToneSonifier()
    s.set_enabled(True)
    s.update_peaks([1000.0])
    first = s._active_freqs

    s.update_peaks([1000.0])

    assert s._active_freqs is first
