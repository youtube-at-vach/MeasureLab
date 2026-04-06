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

    @patch("src.core.analysis.np.linalg.solve")
    def test_sine_fit_residual_linalg_error_fallback(self, mock_solve):
        mock_solve.side_effect = np.linalg.LinAlgError("Singular matrix")
        f = 1000.0
        signal = np.array([1.0, 0.0, -1.0])
        t = np.array([0.0, 0.00025, 0.0005])
        M = np.empty((3, 3))
        fitted_buffer = np.empty(3)
        residual_buffer = np.empty(3)
        with patch("src.core.analysis.np.linalg.lstsq", wraps=np.linalg.lstsq) as mock_lstsq:
            mse = AudioCalc._sine_fit_residual(f, signal, t, M, fitted_buffer, residual_buffer)
            assert mock_solve.called
            mock_lstsq.assert_called_once()
            assert isinstance(mse, float)
            assert not np.isnan(mse)
