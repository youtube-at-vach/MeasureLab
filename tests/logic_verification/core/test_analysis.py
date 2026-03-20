from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from src.core.analysis import AudioCalc

class TestAudioCalc:
    """Tests for the AudioCalc class in src/core/analysis.py"""

    @patch('src.core.analysis.sf.info')
    def test_validate_audio_file_size_valid(self, mock_info):
        mock_info.return_value = MagicMock(frames=1000, channels=2)
        is_valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert is_valid is True
        assert msg == ""

    @patch('src.core.analysis.sf.info')
    def test_validate_audio_file_size_invalid(self, mock_info):
        mock_info.return_value = MagicMock(frames=AudioCalc.MAX_AUDIO_SAMPLES, channels=2)
        is_valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert is_valid is False
        assert "File too large" in msg

    @patch('src.core.analysis.sf.info')
    def test_validate_audio_file_size_error(self, mock_info):
        mock_info.side_effect = Exception("Test Error")
        is_valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert is_valid is False
        assert "Failed to check file size" in msg

    def test_resample_same_rate(self):
        data = np.array([1.0, 2.0, 3.0])
        result = AudioCalc.resample(data, 44100, 44100)
        np.testing.assert_array_equal(result, data)

    def test_resample_invalid_rate(self):
        data = np.array([1.0, 2.0, 3.0])
        result = AudioCalc.resample(data, 0, 44100)
        np.testing.assert_array_equal(result, data)

    def test_resample_downsample(self):
        data = np.ones(100)
        result = AudioCalc.resample(data, 48000, 24000)
        # Length should be ~50
        assert len(result) == 50
        # Values should still be roughly 1.0 (with some edge effects)
        np.testing.assert_allclose(result[10:-10], 1.0, rtol=1e-2)


    def test_design_a_weighting_valid(self):
        sos = AudioCalc.design_a_weighting(48000)
        assert sos is not None
        assert sos.shape == (3, 6) # 3 cascaded biquads

    def test_design_a_weighting_invalid(self):
        with pytest.raises(ValueError, match="Invalid sample rate"):
            AudioCalc.design_a_weighting(0)

    def test_design_c_weighting_valid(self):
        sos = AudioCalc.design_c_weighting(48000)
        assert sos is not None
        assert sos.shape == (2, 6) # 2 cascaded biquads

    def test_design_c_weighting_invalid(self):
        with pytest.raises(ValueError, match="Invalid sample rate"):
            AudioCalc.design_c_weighting(-100)

    def test_bandpass_filter_short_signal(self):
        # Signal too short for padlen
        signal = np.ones(10)
        filtered = AudioCalc.bandpass_filter(signal, 48000)
        np.testing.assert_array_equal(filtered, signal)

    def test_bandpass_filter_valid(self):
        signal = np.ones(100)
        filtered = AudioCalc.bandpass_filter(signal, 48000, 20.0, 20000.0)
        assert len(filtered) == 100

    def test_bandpass_filter_invalid_freqs(self):
        signal = np.ones(100)
        # Invalid: lowcut >= highcut -> sos_factory returns None -> bypass/silence based on on_invalid_sos
        # For bandpass, on_invalid_sos="silence"
        filtered = AudioCalc.bandpass_filter(signal, 48000, 20000.0, 20.0)
        np.testing.assert_array_equal(filtered, np.zeros_like(signal))

    def test_lowpass_filter_valid(self):
        signal = np.ones(100)
        filtered = AudioCalc.lowpass_filter(signal, 48000, 1000.0)
        assert len(filtered) == 100

    def test_highpass_filter_valid(self):
        signal = np.ones(100)
        filtered = AudioCalc.highpass_filter(signal, 48000, 1000.0)
        assert len(filtered) == 100

    def test_optimize_frequency_empty_signal(self):
        result = AudioCalc.optimize_frequency(np.array([]), 48000, 1000.0)
        assert result == 1000.0

    def test_optimize_frequency_valid(self):
        t = np.arange(48000) / 48000.0
        # Generate exactly 1000Hz signal
        signal = np.sin(2 * np.pi * 1000.0 * t)
        # Give a guess slightly off
        best_freq = AudioCalc.optimize_frequency(signal, 48000, 999.5)
        np.testing.assert_allclose(best_freq, 1000.0, rtol=1e-4)

    def test_calculate_thdn_sine_fit_perfect_sine(self):
        t = np.arange(48000) / 48000.0
        signal = np.sin(2 * np.pi * 1000.0 * t)
        thdn_db, fund_rms, nd_rms = AudioCalc.calculate_thdn_sine_fit(signal, 48000, 1000.0)
        # THD+N should be very low for a perfect generated sine
        assert thdn_db < -100.0
        assert fund_rms > 0.0

    def test_analyze_harmonics(self):
        t = np.arange(48000) / 48000.0
        # Fundamental (1kHz) + 2nd harmonic (2kHz)
        signal = np.sin(2 * np.pi * 1000.0 * t) + 0.1 * np.sin(2 * np.pi * 2000.0 * t)
        results = AudioCalc.analyze_harmonics(signal, 1000.0, "hann", 48000)
        assert "basic_wave" in results
        assert "harmonics" in results
        np.testing.assert_allclose(results["basic_wave"]["frequency"], 1000.0, rtol=1e-2)
        # THD should reflect the 10% 2nd harmonic
        assert results["thd_percent"] > 0

    def test_calculate_imd_smpte(self):
        # Dummy spectrum
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)
        # 60Hz and 7kHz
        mag[60] = 1.0
        mag[7000] = 0.5
        # Sidebands at 7000 +/- 60
        mag[7060] = 0.05
        mag[6940] = 0.05

        results = AudioCalc.calculate_imd_smpte(mag, freqs, 60.0, 7000.0)
        assert "imd" in results
        assert results["imd"] > 0

    def test_calculate_imd_ccif(self):
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)
        # 19kHz and 20kHz
        mag[19000] = 1.0
        mag[20000] = 1.0
        # d2 distortion product at 1kHz
        mag[1000] = 0.1

        results = AudioCalc.calculate_imd_ccif(mag, freqs, 19000.0, 20000.0)
        assert "imd" in results
        assert results["imd"] > 0

    def test_calculate_multitone_tdn(self):
        freqs = np.linspace(0, 24000, 24001)
        mag = np.ones_like(freqs) * 0.01 # Noise floor
        tone_freqs = [1000.0, 2000.0, 3000.0]
        for f in tone_freqs:
            mag[int(f)] = 1.0

        results = AudioCalc.calculate_multitone_tdn(mag, freqs, tone_freqs)
        assert "tdn" in results
        assert results["tdn"] > 0

    def test_calculate_spdr(self):
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)
        mag[1000] = 1.0 # Fundamental
        mag[5000] = 0.01 # Spur

        results = AudioCalc.calculate_spdr(mag, freqs, 1000.0)
        assert "spdr_db" in results
        # 20 * log10(1 / 0.01) = 40dB
        np.testing.assert_allclose(results["spdr_db"], 40.0)

    def test_calculate_pim(self):
        freqs = np.linspace(0, 24000, 24001)
        mag = np.zeros_like(freqs)
        mag[1000] = 1.0
        mag[2000] = 1.0
        # IM3: 2f1-f2=0, 2f2-f1=3000
        mag[3000] = 0.1

        results = AudioCalc.calculate_pim(mag, freqs, 1000.0, 2000.0)
        assert "pim_db" in results

    def test_calculate_noise_profile(self):
        freqs = np.linspace(0, 24000, 24001)
        mag = np.ones_like(freqs) * 0.001
        mag[50] = 0.1 # Hum

        results = AudioCalc.calculate_noise_profile(mag, freqs, 48000)
        assert "hum_rms" in results
        assert results["hum_rms"] > 0
        assert "noise_rms_20k" in results

    def test_calculate_lockin_measurement(self):
        t = np.arange(48000) / 48000.0
        signal = np.sin(2 * np.pi * 1000.0 * t)

        mag, phase = AudioCalc.calculate_lockin_measurement(signal, 1000.0, 48000)
        # For a sine wave of amp 1, lock-in will give roughly 1 (depends on scaling and window, often rms or amplitude)
        assert mag > 0.0
        assert isinstance(phase, float)
