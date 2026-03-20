import pytest
np = pytest.importorskip("numpy")

try:
    from src.core.analysis import AudioCalc
except ImportError:
    pytest.skip("skipping tests because src.core.analysis could not be imported (missing scipy?)", allow_module_level=True)

def test_bandpass_filter_short_signal():
    """Verify that signals shorter than 52 samples are returned as is."""
    sampling_rate = 48000

    # Test with exactly 51 samples
    signal = np.zeros(51)
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, 20.0, 20000.0)
    assert np.array_equal(filtered, signal)

    # Test with shorter signal
    signal = np.zeros(10)
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, 20.0, 20000.0)
    assert np.array_equal(filtered, signal)

    # Test with exactly 52 samples (should process)
    # Since it's zeros, output should be zeros (due to filter stability), but verify type/shape
    signal = np.zeros(52)
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, 20.0, 20000.0)
    assert len(filtered) == 52
    assert np.allclose(filtered, np.zeros(52))

def test_bandpass_filter_attenuation():
    """Verify that frequencies outside the passband are attenuated."""
    sampling_rate = 48000
    duration = 0.1
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)

    # Generate signals
    # Low freq: 10 Hz (well below 200 Hz cutoff)
    low_freq_signal = np.sin(2 * np.pi * 10 * t)
    # High freq: 25 kHz (well above 2000 Hz cutoff)
    high_freq_signal = np.sin(2 * np.pi * 25000 * t)
    # Passband: 1000 Hz (well within 200-2000 Hz)
    passband_signal = np.sin(2 * np.pi * 1000 * t)

    # Filter with 200Hz - 2000Hz passband
    filtered_low = AudioCalc.bandpass_filter(low_freq_signal, sampling_rate, lowcut=200.0, highcut=2000.0)
    filtered_high = AudioCalc.bandpass_filter(high_freq_signal, sampling_rate, lowcut=200.0, highcut=2000.0)
    filtered_pass = AudioCalc.bandpass_filter(passband_signal, sampling_rate, lowcut=200.0, highcut=2000.0)

    # Check RMS values (ignore initial transient by trimming)
    trim = int(sampling_rate * 0.01) # 10ms trim

    def get_rms(sig):
        return np.sqrt(np.mean(sig[trim:-trim]**2))

    rms_low = get_rms(filtered_low)
    rms_high = get_rms(filtered_high)
    rms_pass = get_rms(filtered_pass)

    orig_rms_low = np.sqrt(np.mean(low_freq_signal**2))
    orig_rms_high = np.sqrt(np.mean(high_freq_signal**2))
    orig_rms_pass = np.sqrt(np.mean(passband_signal**2))

    # Expect significant attenuation (>20dB = 0.1x amplitude)
    # Butterworth 8th order is very steep, so we expect much better than 20dB
    assert rms_low < orig_rms_low * 0.1, f"Low frequency not attenuated enough: {rms_low} vs {orig_rms_low}"
    assert rms_high < orig_rms_high * 0.1, f"High frequency not attenuated enough: {rms_high} vs {orig_rms_high}"

    # Expect preservation for in-band signals (allow small loss/ripple)
    assert rms_pass > orig_rms_pass * 0.9, f"Passband signal attenuated too much: {rms_pass} vs {orig_rms_pass}"

def test_bandpass_filter_invalid_bounds():
    """Verify behavior with invalid bounds."""
    sampling_rate = 48000
    signal = np.random.randn(1000)

    # Case 1: lowcut >= highcut
    # Should return silence (zeros) as passband is empty
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, lowcut=5000.0, highcut=100.0)
    assert np.allclose(filtered, 0)

    # Case 2: lowcut = highcut
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, lowcut=1000.0, highcut=1000.0)
    assert np.allclose(filtered, 0)

def test_bandpass_filter_nyquist_handling():
    """Verify behavior near Nyquist frequency."""
    sampling_rate = 48000
    nyquist = sampling_rate / 2
    signal = np.random.randn(1000)

    # Case: highcut > nyquist
    # The implementation clamps highcut to nyquist - 1
    # We test that it runs without error and returns something different (filtered)
    filtered = AudioCalc.bandpass_filter(signal, sampling_rate, lowcut=20.0, highcut=nyquist + 1000.0)

    assert len(filtered) == len(signal)
    # It should not be identical to input (it filters low frequencies at least)
    assert not np.array_equal(filtered, signal)

    # Case: lowcut clamped (negative lowcut)
    # Implementation clamps lowcut to 0.1
    filtered_neg = AudioCalc.bandpass_filter(signal, sampling_rate, lowcut=-100.0, highcut=1000.0)
    assert len(filtered_neg) == len(signal)
    assert not np.array_equal(filtered_neg, signal)

def test_lowpass_filter_attenuation():
    """Verify that frequencies above the cutoff are attenuated."""
    sampling_rate = 48000
    duration = 0.1
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)

    # Low freq: 100 Hz (well below 1000 Hz cutoff)
    low_freq_signal = np.sin(2 * np.pi * 100 * t)
    # High freq: 5000 Hz (well above 1000 Hz cutoff)
    high_freq_signal = np.sin(2 * np.pi * 5000 * t)

    # Filter with 1000 Hz cutoff
    filtered_low = AudioCalc.lowpass_filter(low_freq_signal, sampling_rate, cutoff=1000.0)
    filtered_high = AudioCalc.lowpass_filter(high_freq_signal, sampling_rate, cutoff=1000.0)

    # Check RMS values
    trim = int(sampling_rate * 0.01)

    def get_rms(sig):
        return np.sqrt(np.mean(sig[trim:-trim]**2))

    rms_low = get_rms(filtered_low)
    rms_high = get_rms(filtered_high)

    orig_rms_low = np.sqrt(np.mean(low_freq_signal**2))
    orig_rms_high = np.sqrt(np.mean(high_freq_signal**2))

    # Expect significant attenuation for high freq
    assert rms_high < orig_rms_high * 0.1, f"High frequency not attenuated enough: {rms_high} vs {orig_rms_high}"
    # Expect preservation for low freq
    assert rms_low > orig_rms_low * 0.9, f"Low frequency attenuated too much: {rms_low} vs {orig_rms_low}"


def test_lowpass_filter_short_signal():
    """Verify that signals shorter than 28 samples are returned as is."""
    sampling_rate = 48000

    # Test with exactly 27 samples
    signal = np.zeros(27)
    filtered = AudioCalc.lowpass_filter(signal, sampling_rate, cutoff=1000.0)
    assert np.array_equal(filtered, signal)

    # Test with shorter signal
    signal = np.zeros(10)
    filtered = AudioCalc.lowpass_filter(signal, sampling_rate, cutoff=1000.0)
    assert np.array_equal(filtered, signal)


def test_lowpass_filter_edge_cases():
    """Verify behavior with edge cases."""
    sampling_rate = 48000
    signal = np.random.randn(1000)

    # Case: cutoff > nyquist
    filtered = AudioCalc.lowpass_filter(signal, sampling_rate, cutoff=sampling_rate + 1000.0)
    assert len(filtered) == len(signal)
    # Should not crash

    # Case: cutoff <= 0
    filtered = AudioCalc.lowpass_filter(signal, sampling_rate, cutoff=-100.0)
    assert len(filtered) == len(signal)
    # Should not crash


def test_highpass_filter_attenuation():
    """Verify that frequencies below the cutoff are attenuated."""
    sampling_rate = 48000
    duration = 0.1
    t = np.linspace(0, duration, int(sampling_rate * duration), endpoint=False)

    # Low freq: 100 Hz (well below 1000 Hz cutoff)
    low_freq_signal = np.sin(2 * np.pi * 100 * t)
    # High freq: 5000 Hz (well above 1000 Hz cutoff)
    high_freq_signal = np.sin(2 * np.pi * 5000 * t)

    # Filter with 1000 Hz cutoff
    filtered_low = AudioCalc.highpass_filter(low_freq_signal, sampling_rate, cutoff=1000.0)
    filtered_high = AudioCalc.highpass_filter(high_freq_signal, sampling_rate, cutoff=1000.0)

    # Check RMS values
    trim = int(sampling_rate * 0.01)

    def get_rms(sig):
        return np.sqrt(np.mean(sig[trim:-trim]**2))

    rms_low = get_rms(filtered_low)
    rms_high = get_rms(filtered_high)

    orig_rms_low = np.sqrt(np.mean(low_freq_signal**2))
    orig_rms_high = np.sqrt(np.mean(high_freq_signal**2))

    # Expect significant attenuation for low freq
    assert rms_low < orig_rms_low * 0.1, f"Low frequency not attenuated enough: {rms_low} vs {orig_rms_low}"
    # Expect preservation for high freq
    assert rms_high > orig_rms_high * 0.9, f"High frequency attenuated too much: {rms_high} vs {orig_rms_high}"


def test_highpass_filter_short_signal():
    """Verify that signals shorter than 28 samples are returned as is."""
    sampling_rate = 48000

    # Test with exactly 27 samples
    signal = np.zeros(27)
    filtered = AudioCalc.highpass_filter(signal, sampling_rate, cutoff=1000.0)
    assert np.array_equal(filtered, signal)

    # Test with shorter signal
    signal = np.zeros(10)
    filtered = AudioCalc.highpass_filter(signal, sampling_rate, cutoff=1000.0)
    assert np.array_equal(filtered, signal)


def test_highpass_filter_edge_cases():
    """Verify behavior with edge cases."""
    sampling_rate = 48000
    signal = np.random.randn(1000)

    # Case: cutoff > nyquist
    filtered = AudioCalc.highpass_filter(signal, sampling_rate, cutoff=sampling_rate + 1000.0)
    assert len(filtered) == len(signal)
    # Should not crash

    # Case: cutoff <= 0
    filtered = AudioCalc.highpass_filter(signal, sampling_rate, cutoff=-100.0)
    assert len(filtered) == len(signal)
    # Should not crash


# Trigger CI
