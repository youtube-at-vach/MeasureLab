from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from src.core.analysis import AudioCalc


class TestAudioCalc:
    """Tests for the AudioCalc class in src/core/analysis.py"""

    @patch("src.core.analysis.sf.info")
    def test_validate_audio_file_size_valid(self, mock_info):
        mock_info.return_value = MagicMock(frames=1000, channels=2)
        is_valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert is_valid is True
        assert msg == ""

    @patch("src.core.analysis.sf.info")
    def test_validate_audio_file_size_invalid(self, mock_info):
        mock_info.return_value = MagicMock(frames=AudioCalc.MAX_AUDIO_SAMPLES, channels=2)
        is_valid, msg = AudioCalc.validate_audio_file_size("dummy.wav")
        assert is_valid is False
        assert "File too large" in msg

    @patch("src.core.analysis.sf.info")
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
        assert sos.shape == (3, 6)  # 3 cascaded biquads

    def test_design_a_weighting_invalid(self):
        with pytest.raises(ValueError, match="Invalid sample rate"):
            AudioCalc.design_a_weighting(0)

    def test_design_c_weighting_valid(self):
        sos = AudioCalc.design_c_weighting(48000)
        assert sos is not None
        assert sos.shape == (2, 6)  # 2 cascaded biquads

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
