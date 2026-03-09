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
    s.update_spectrum([1000.0], [0.0], [1000.0])

    outdata = np.zeros((1024, 2))
    s.process(outdata)

    # Initial amp is 0, target is 1, so it should start producing sound soon
    assert np.any(outdata != 0.0)


def test_peak_tone_sonifier_folds_to_audible_band():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.set_max_peaks(2)
    s.update_spectrum([32000.0, 40.0], [0.0, 0.0], [32000.0, 40.0])

    # Check target frequencies in oscillators
    target_freqs = s._oscillators[:2, 1]
    assert np.all(target_freqs >= s.AUDIBLE_MIN_FREQ)
    assert np.all(target_freqs <= s.AUDIBLE_MAX_FREQ)


def test_peak_tone_sonifier_smooth_amplitude_transition():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.update_spectrum([1000.0], [0.0], [1000.0])
    
    # First block: should fade in from 0
    outdata = np.zeros((1024, 2))
    s.process(outdata)
    block1_max = np.max(np.abs(outdata))
    
    # Second block: should continue to increase in amplitude
    outdata.fill(0.0)
    s.process(outdata)
    block2_max = np.max(np.abs(outdata))
    
    assert block2_max > block1_max


def test_peak_tone_sonifier_peak_tracking():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.update_spectrum([1000.0], [0.0], [1000.0])
    
    # Process once to establish frequency
    outdata = np.zeros((1024, 2))
    s.process(outdata)
    
    initial_f = s._oscillators[0, 0]
    assert abs(initial_f - 1000.0) < 50.0 # Significant progress towards 1000
    
    # Update with a nearby peak (1100)
    s.update_spectrum([1100.0], [0.0], [1100.0])
    
    # Check that it's tracking (same oscillator index)
    assert s._oscillators[0, 1] == 1100.0
    assert s._oscillators[0, 3] == 1.0


def test_peak_tone_sonifier_fade_out():
    s = PeakToneSonifier(sample_rate=48000)
    s.set_enabled(True)
    s.update_spectrum([1000.0], [0.0], [1000.0])
    
    # Run long enough to reach some amplitude
    for _ in range(20):
        s.process(np.zeros((1024, 2)))
        
    amp_before = s._oscillators[0, 2]
    assert amp_before > 0.5
    
    # Remove peak
    s.update_spectrum([], [], [])
    assert s._oscillators[0, 3] == 0.0 # Target amp is now 0
    
    # Process and check fade out
    s.process(np.zeros((1024, 2)))
    amp_after = s._oscillators[0, 2]
    assert amp_after < amp_before
